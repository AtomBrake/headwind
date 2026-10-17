import Foundation
import Observation
import WatchConnectivity

/// iPhone end of the Watch link. Rides recorded on the Watch arrive as GPX file transfers (queued by the
/// system, delivered even if this app wasn't running) and go into the RideStore to upload with the phone's
/// pairing; the Watch never talks to the server itself. In the other direction the phone tells the Watch
/// which units to show and whether it's paired.
@MainActor
@Observable
final class WatchBridge: NSObject {
    @ObservationIgnored private let store: RideStore
    /// Called after a Watch ride is stored, to start its upload.
    @ObservationIgnored var onRideReceived: (() -> Void)?
    /// The last Watch ride that couldn't be stored on the phone, for the Record tab to show.
    private(set) var lastError: AppError?
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

    func updateWatch(units: String?, paired: Bool) {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated,
              WCSession.default.isPaired, WCSession.default.isWatchAppInstalled else { return }
        try? WCSession.default.updateApplicationContext([WatchLink.unitsKey: units ?? "metric", WatchLink.pairedKey: paired])
    }

    /// Move every held ride into the RideStore. One that can't be stored stays in the inbox for the next try.
    func drainInbox() {
        let files = (try? FileManager.default.contentsOfDirectory(at: inbox, includingPropertiesForKeys: nil)) ?? []
        var adopted = false
        for gpx in files where gpx.pathExtension == "gpx" {
            let sidecar = gpx.deletingPathExtension().appendingPathExtension("json")
            // The summary is only for the list; if it's missing the server still works the ride out from the GPX.
            let summary = (try? Data(contentsOf: sidecar)).flatMap { try? JSONDecoder().decode(RideSummary.self, from: $0) }
                ?? RideSummary(start: .now, distance: 0, movingTime: 0, elapsedTime: 0, elevationGain: 0)
            do throws(AppError) {
                try store.adopt(file: gpx, summary: summary, source: .watch)
                try? FileManager.default.removeItem(at: sidecar)
                lastError = nil
                adopted = true
            } catch {
                lastError = error
            }
        }
        if adopted { onRideReceived?() }
    }

    /// Move a received file into the inbox with its summary beside it. Must be synchronous: the system deletes
    /// the received file when the delegate method returns.
    nonisolated private func hold(_ file: URL, summary: RideSummary?) throws {
        // The summary goes first, so a drain running meanwhile never sees the GPX without it.
        let gpx = inbox.appending(path: "\(UUID().uuidString).gpx")
        let sidecar = gpx.deletingPathExtension().appendingPathExtension("json")
        if let summary, let data = try? JSONEncoder().encode(summary) {
            try? data.write(to: sidecar, options: .atomic)
        }
        do {
            try FileManager.default.moveItem(at: file, to: gpx)
        } catch {
            try? FileManager.default.removeItem(at: sidecar)
            throw error
        }
    }
}

extension WatchBridge: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {}
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        session.activate()   // the user switched to another Watch
    }

    nonisolated func session(_ session: WCSession, didReceive file: WCSessionFile) {
        guard file.metadata?[WatchLink.kindKey] as? String == WatchLink.rideKind else { return }
        let summary = file.metadata.flatMap(RideSummary.init(dictionary:))
        do {
            try hold(file.fileURL, summary: summary)
        } catch {
            // The Watch has already let go of it, so the least we can do is say so.
            let failure = AppError.storage(underlying: error)
            Task { @MainActor in self.lastError = failure }
            return
        }
        Task { @MainActor in self.drainInbox() }
    }
}
