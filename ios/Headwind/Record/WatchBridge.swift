import Foundation
import Observation
import WatchConnectivity

/// iPhone end of the Watch link. Rides recorded on the Watch arrive as GPX file transfers (queued by the
/// system, delivered even if this app wasn't running), timed-only sessions as their summary, and go into the RideStore to upload with
/// the phone's pairing. In the other direction the phone tells the Watch which units to show, whether it's paired, and the rider's bikes
/// for its bike picker, and gives it a token of its own (POST /api/v1/devices/watch) so it can upload a ride itself when the phone isn't
/// with it. Each recording carries the Watch's id for it, so whichever way it arrives the server keeps one copy.
@MainActor
@Observable
final class WatchBridge: NSObject {
    @ObservationIgnored private let store: RideStore
    /// Called after a Watch ride is stored, to start its upload.
    @ObservationIgnored var onRideReceived: (() -> Void)?
    /// The last Watch ride that couldn't be stored on the phone, for the Record tab to show.
    private(set) var lastError: AppError?
    /// The latest units/paired/bikes context for the Watch, kept until the session can take it.
    @ObservationIgnored private var context: (units: String, paired: Bool, bikes: [Bike])?
    /// Where arriving rides are held (GPX plus a summary .json) until the RideStore takes them. Once a transfer
    /// is received the Watch deletes its copy, so this is in Application Support, not a purgeable temp directory.
    nonisolated let inbox: URL

    static var standardInbox: URL {
        let dir = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        return dir.appending(path: "WatchInbox", directoryHint: .isDirectory)
    }

    init(store: RideStore, inbox: URL = WatchBridge.standardInbox) {
        self.store = store
        self.inbox = inbox
        super.init()
        try? FileManager.default.createDirectory(at: inbox, withIntermediateDirectories: true)
        drainInbox()   // anything a previous launch received but couldn't store
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func updateWatch(units: String?, paired: Bool, bikes: [Bike]) {
        context = (units ?? "metric", paired, bikes)
        sendContext()
    }

    // MARK: - The Watch's own pairing

    @ObservationIgnored private let defaults = UserDefaults.standard
    private static let provisionedKey = "watch-pairing-for", lastTryKey = "watch-pairing-tried"

    /// Make sure the Watch has a token of its own for the server this phone is paired with: one is made the first time, and again after
    /// pairing with another server. Unpaired, the Watch is told to forget its token. An older server without the endpoint is asked again a
    /// day later rather than on every launch.
    func provisionWatch(using session: Session) async {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated,
              WCSession.default.isPaired, WCSession.default.isWatchAppInstalled else { return }
        guard let pairing = session.pairing else {
            if defaults.string(forKey: Self.provisionedKey) != nil {
                WCSession.default.transferUserInfo([WatchLink.forgetKey: true])
                defaults.removeObject(forKey: Self.provisionedKey)
            }
            return
        }
        let marker = pairing.server.absoluteString
        guard defaults.string(forKey: Self.provisionedKey) != marker else { return }
        if let tried = defaults.object(forKey: Self.lastTryKey) as? Date, -tried.timeIntervalSinceNow < 24 * 3600 { return }
        defaults.set(Date(), forKey: Self.lastTryKey)
        do throws(AppError) {
            let reply = try await session.call { client async throws(AppError) in
                try await client.post("devices/watch", json: [String: String](), as: WatchToken.self)
            }
            // transferUserInfo is queued and delivered once, encrypted, even if the Watch app isn't running.
            WCSession.default.transferUserInfo([WatchLink.watchServerKey: marker, WatchLink.watchTokenKey: reply.token])
            defaults.set(marker, forKey: Self.provisionedKey)
            defaults.removeObject(forKey: Self.lastTryKey)
        } catch {
            // Offline, or a server from before /devices/watch: the Watch keeps sending through the phone, which always works.
        }
    }

    /// Send the latest context if the session is ready; otherwise activation or the Watch app being installed
    /// sends it later.
    private func sendContext() {
        guard let context, WCSession.isSupported(), WCSession.default.activationState == .activated,
              WCSession.default.isPaired, WCSession.default.isWatchAppInstalled else { return }
        try? WCSession.default.updateApplicationContext([WatchLink.unitsKey: context.units, WatchLink.pairedKey: context.paired,
                                                         WatchLink.bikesKey: context.bikes.map(\.dictionary)])
    }

    /// Move every held ride and session into the RideStore. One that can't be stored stays in the inbox for the next try.
    func drainInbox() {
        let files = (try? FileManager.default.contentsOfDirectory(at: inbox, includingPropertiesForKeys: nil)) ?? []
        var adopted = false
        for file in files where file.pathExtension == "gpx" || file.pathExtension == WatchLink.sessionKind {
            let sidecar = file.deletingPathExtension().appendingPathExtension("json")
            let id = UUID(uuidString: file.deletingPathExtension().lastPathComponent) ?? UUID()
            let held = (try? Data(contentsOf: file.pathExtension == "gpx" ? sidecar : file))
                .flatMap { try? JSONDecoder().decode(RideSummary.self, from: $0) }
            do throws(AppError) {
                if file.pathExtension == "gpx" {
                    // The summary is only for the list; if it's missing the server still works the ride out from the GPX.
                    try store.adopt(file: file, summary: held ?? RideSummary(start: .now, distance: 0, movingTime: 0, elapsedTime: 0, elevationGain: 0),
                                    source: .watch, id: id)
                    try? FileManager.default.removeItem(at: sidecar)
                } else if let held {
                    try store.addSession(summary: held, source: .watch, id: id)
                    try? FileManager.default.removeItem(at: file)
                } else {
                    try? FileManager.default.removeItem(at: file)     // a session is nothing without its summary
                    continue
                }
                lastError = nil
                adopted = true
            } catch {
                lastError = error
            }
        }
        if adopted { onRideReceived?() }
    }

    /// Move a received file into the inbox, named by the Watch's id for the recording, with its summary beside it (a session's file is its
    /// summary). Must be synchronous: the system deletes the received file when the delegate method returns.
    nonisolated private func hold(_ file: URL, summary: RideSummary?, id: UUID?, kind: String) throws {
        let name = (id ?? UUID()).uuidString
        if kind == WatchLink.sessionKind {
            guard let summary, let data = try? JSONEncoder().encode(summary) else { throw AppError.unexpectedResponse }
            try data.write(to: inbox.appending(path: "\(name).\(WatchLink.sessionKind)"), options: .atomic)
            return
        }
        // The summary goes first, so a drain running meanwhile never sees the GPX without it.
        let gpx = inbox.appending(path: "\(name).gpx")
        let sidecar = gpx.deletingPathExtension().appendingPathExtension("json")
        if let summary, let data = try? JSONEncoder().encode(summary) {
            try? data.write(to: sidecar, options: .atomic)
        }
        do {
            if FileManager.default.fileExists(atPath: gpx.path()) { try FileManager.default.removeItem(at: gpx) }   // sent twice: the same ride
            try FileManager.default.moveItem(at: file, to: gpx)
        } catch {
            try? FileManager.default.removeItem(at: sidecar)
            throw error
        }
    }
}

extension WatchBridge: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        Task { @MainActor in self.sendContext() }
    }
    nonisolated func sessionWatchStateDidChange(_ session: WCSession) {
        Task { @MainActor in self.sendContext() }   // e.g. the Watch app was just installed
    }
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        session.activate()   // the user switched to another Watch
    }

    nonisolated func session(_ session: WCSession, didReceive file: WCSessionFile) {
        guard let kind = file.metadata?[WatchLink.kindKey] as? String, kind == WatchLink.rideKind || kind == WatchLink.sessionKind else { return }
        let summary = file.metadata.flatMap(RideSummary.init(dictionary:))
        let id = (file.metadata?[WatchLink.idKey] as? String).flatMap(UUID.init(uuidString:))
        do {
            try hold(file.fileURL, summary: summary, id: id, kind: kind)
        } catch {
            // The Watch has already let go of it, so the least we can do is say so.
            let failure = AppError.storage(underlying: error)
            Task { @MainActor in self.lastError = failure }
            return
        }
        Task { @MainActor in self.drainInbox() }
    }
}

/// POST /api/v1/devices/watch reply.
private struct WatchToken: Decodable, Sendable {
    var token: String
}
