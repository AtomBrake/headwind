import Foundation
import Observation
import WatchConnectivity

/// Watch end of the iPhone link. Finished rides go to the phone with transferFile, which the system queues and
/// delivers whenever the phone is reachable, even hours later, so riding without the phone is fine.
/// The phone sends back the server's units, whether it's paired and the rider's bikes, and a token of the Watch's own.
///
/// With that token the Watch also uploads a ride itself, over Wi-Fi or cellular, when the phone hasn't taken it within `directGrace`
/// (it's out of range). Whichever gets there first, the server keeps one copy: both send the recording's id as its client_id, a ride's
/// GPX is matched by content, and once the Watch's own upload succeeds the queued transfer is cancelled so the phone doesn't send it again.
@MainActor
@Observable
final class PhoneLink: NSObject {
    private(set) var units = Units(system: "metric")
    private(set) var phonePaired = true
    private(set) var bikes: [Bike] = []
    /// Rides in the outbox: not yet confirmed delivered to the phone or the server.
    private(set) var waitingToSend = 0
    /// Why rides are stuck in the outbox (e.g. Headwind isn't installed on the iPhone); nil while sending normally.
    private(set) var sendProblem: String?
    /// The Watch's own pairing, from the phone; nil until the phone has made one (or on an older server).
    private(set) var pairing: Pairing?
    /// Set when the last ride went straight to the server from the Watch.
    private(set) var lastDirect: Date?
    /// Failed attempts per outbox file, for backing off, and the files waiting out a backoff.
    @ObservationIgnored private var failures: [String: Int] = [:]
    @ObservationIgnored private var retrying: Set<String> = []
    @ObservationIgnored private var directFailures: [String: Int] = [:]
    @ObservationIgnored private var directPending: Set<String> = []
    @ObservationIgnored private let keychain = KeychainPairingStore(service: "io.github.atombrake.headwind.watch", account: "watch")

    /// How long the phone has to take a ride before the Watch sends it itself: long enough for a phone in the jersey pocket, short enough
    /// that a ride from a run without the phone is on the server before the Watch is back on its charger.
    static let directGrace: Duration = .seconds(45)

    private let outbox: URL = {
        let dir = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        let url = dir.appending(path: "Outbox", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()

    override init() {
        super.init()
        pairing = keychain.load()
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    /// Queue a ride's GPX for the phone (and, after the grace period, the server). The file is named by the recording's id.
    func send(gpx: Data, summary: RideSummary) throws(AppError) {
        let id = UUID()
        let file = outbox.appending(path: "\(id.uuidString).gpx")
        do {
            try gpx.write(to: file, options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
        // Kept so the ride can be sent again on a later launch; without it the phone falls back to the GPX alone.
        try? JSONEncoder().encode(summary).write(to: sidecar(file), options: .atomic)
        transfer(file, summary: summary)
        scheduleDirect(file)
    }

    /// Queue a timed-only session: its file is its summary.
    func send(session summary: RideSummary) throws(AppError) {
        let file = outbox.appending(path: "\(UUID().uuidString).\(WatchLink.sessionKind)")
        do {
            try JSONEncoder().encode(summary).write(to: file, options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
        transfer(file, summary: summary)
        scheduleDirect(file)
    }

    private func transfer(_ file: URL, summary: RideSummary?) {
        var metadata = summary?.dictionary ?? [:]
        metadata[WatchLink.kindKey] = file.pathExtension == WatchLink.sessionKind ? WatchLink.sessionKind : WatchLink.rideKind
        metadata[WatchLink.idKey] = file.deletingPathExtension().lastPathComponent
        WCSession.default.transferFile(file, metadata: metadata)
        refreshCount()
    }

    /// Queue every outbox ride the system isn't already sending: ones given up on after a permanent error, or
    /// left waiting out a backoff when the app was last closed. Each also gets its direct upload again.
    private func resendOutbox() {
        let queued = Set(WCSession.default.outstandingFileTransfers.map { $0.file.fileURL.lastPathComponent })
        for file in outboxRides() {
            if !queued.contains(file.lastPathComponent) && !retrying.contains(file.lastPathComponent) {
                transfer(file, summary: summary(of: file))
            }
            scheduleDirect(file)
        }
    }

    /// Try a failed transfer again after 15 s, doubling each time up to 30 min, so a phone that keeps refusing
    /// doesn't keep the radio busy.
    private func retry(_ file: URL, summary: RideSummary?) {
        let name = file.lastPathComponent
        let attempt = failures[name, default: 0] + 1
        failures[name] = attempt
        let delay = Self.backoff(attempt)
        retrying.insert(name)
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self else { return }
            self.retrying.remove(name)
            guard FileManager.default.fileExists(atPath: file.path) else { return }
            self.transfer(file, summary: summary)
        }
    }

    /// 15 s, 30 s, 1 min… up to 30 min.
    nonisolated static func backoff(_ attempt: Int) -> Double {
        min(15 * Double(1 << min(max(attempt, 1) - 1, 7)), 30 * 60)
    }

    // MARK: - Straight to the server

    /// After the grace period, upload the ride from the Watch if the phone hasn't taken it. Cellular on the Watch is expensive, so each
    /// failure backs off as transfers do, and only one attempt per file is ever waiting.
    private func scheduleDirect(_ file: URL, after attempt: Int = 0) {
        let name = file.lastPathComponent
        guard pairing != nil, !directPending.contains(name) else { return }
        directPending.insert(name)
        Task { [weak self] in
            try? await Task.sleep(for: attempt == 0 ? Self.directGrace : .seconds(Self.backoff(attempt)))
            guard let self else { return }
            self.directPending.remove(name)
            await self.uploadDirect(file)
        }
    }

    private func uploadDirect(_ file: URL) async {
        guard let pairing, FileManager.default.fileExists(atPath: file.path()) else { return }   // the phone took it meanwhile
        let isSession = file.pathExtension == WatchLink.sessionKind
        guard let summary = summary(of: file), let id = UUID(uuidString: file.deletingPathExtension().lastPathComponent) else { return }
        let gpx = isSession ? nil : try? Data(contentsOf: file)
        do throws(AppError) {
            _ = try await Uploader.upload(summary: summary, id: id, name: GPXWriter.rideName(summary), gpx: gpx, with: APIClient(pairing: pairing))
            // On the server: stop the phone sending it again, and let it go here.
            for transfer in WCSession.default.outstandingFileTransfers where transfer.file.fileURL.lastPathComponent == file.lastPathComponent {
                transfer.cancel()
            }
            lastDirect = .now
            delivered(file)
            refreshCount()
        } catch {
            switch error {
            case .unauthorised:
                forgetPairing()     // revoked on the Phones page: back to sending through the phone only
            case _ where error.isRejection:
                break               // the server can't read it; the phone's copy will say so in its list
            default:
                let attempt = directFailures[file.lastPathComponent, default: 0] + 1
                directFailures[file.lastPathComponent] = attempt
                scheduleDirect(file, after: attempt)
            }
        }
    }

    /// The pairing the phone made for the Watch, checked as a pairing link is (https only, a well-formed token).
    private func adopt(server: String, token: String) {
        guard let made = try? PairLink.make(server: server, token: token) else { return }
        keychain.save(made)
        pairing = made
        resendOutbox()
    }

    private func forgetPairing() {
        keychain.clear()
        pairing = nil
    }

    // MARK: - Outbox

    private func delivered(_ file: URL) {
        try? FileManager.default.removeItem(at: file)
        try? FileManager.default.removeItem(at: sidecar(file))
        failures[file.lastPathComponent] = nil
        directFailures[file.lastPathComponent] = nil
        sendProblem = nil
    }

    private func outboxRides() -> [URL] {
        let files = (try? FileManager.default.contentsOfDirectory(at: outbox, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.pathExtension == "gpx" || $0.pathExtension == WatchLink.sessionKind }
    }

    /// A ride's summary sits beside its GPX; a session's file is its summary.
    private func sidecar(_ file: URL) -> URL {
        file.pathExtension == WatchLink.sessionKind ? file : file.deletingPathExtension().appendingPathExtension("json")
    }

    private func summary(of file: URL) -> RideSummary? {
        (try? Data(contentsOf: sidecar(file))).flatMap { try? JSONDecoder().decode(RideSummary.self, from: $0) }
    }

    private func refreshCount() {
        waitingToSend = outboxRides().count
    }

    /// Errors no retry will fix, e.g. Headwind isn't installed on the iPhone. Anything else (out of range,
    /// session not active yet, timed out) is worth trying again.
    nonisolated private static func isPermanent(_ error: Error) -> Bool {
        guard let code = (error as? WCError)?.code else { return false }
        switch code {
        case .sessionNotSupported, .sessionMissingDelegate, .deviceNotPaired, .companionAppNotInstalled,
             .watchAppNotInstalled, .invalidParameter, .payloadTooLarge, .payloadUnsupportedTypes, .fileAccessDenied:
            return true
        default:
            return false
        }
    }

    private func apply(units system: String?, paired: Bool?, bikes: [Bike]?) {
        if let system { units = Units(system: system) }
        if let paired { phonePaired = paired }
        if let bikes { self.bikes = bikes }
    }

    /// The bikes in an application context, or nil if it has none (an older iPhone app).
    nonisolated private static func bikes(in context: [String: Any]) -> [Bike]? {
        (context[WatchLink.bikesKey] as? [[String: Any]])?.compactMap(Bike.init(dictionary:))
    }
}

extension PhoneLink: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        let context = session.receivedApplicationContext
        let units = context[WatchLink.unitsKey] as? String, paired = context[WatchLink.pairedKey] as? Bool
        let bikes = Self.bikes(in: context)
        let activated = state == .activated
        Task { @MainActor in
            self.apply(units: units, paired: paired, bikes: bikes)
            if activated { self.resendOutbox() }
            self.refreshCount()
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveApplicationContext context: [String: Any]) {
        let units = context[WatchLink.unitsKey] as? String, paired = context[WatchLink.pairedKey] as? Bool
        let bikes = Self.bikes(in: context)
        Task { @MainActor in self.apply(units: units, paired: paired, bikes: bikes) }
    }

    /// The Watch's own pairing (or word to forget it), sent once by the phone with transferUserInfo.
    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        let forget = userInfo[WatchLink.forgetKey] as? Bool == true
        let server = userInfo[WatchLink.watchServerKey] as? String, token = userInfo[WatchLink.watchTokenKey] as? String
        Task { @MainActor in
            if forget {
                self.forgetPairing()
            } else if let server, let token {
                self.adopt(server: server, token: token)
            }
        }
    }

    /// A transfer the Watch cancelled after uploading the ride itself has already let go of its file, so a retry finds nothing to send.
    nonisolated func session(_ session: WCSession, didFinish fileTransfer: WCSessionFileTransfer, error: Error?) {
        let url = fileTransfer.file.fileURL
        let summary = fileTransfer.file.metadata.flatMap(RideSummary.init(dictionary:))
        let permanent = error.map(Self.isPermanent), message = error?.localizedDescription
        Task { @MainActor in
            switch permanent {
            case nil:
                self.delivered(url)
            case true?:
                // Retrying won't help; the ride stays in the outbox and is sent again on the next launch.
                self.sendProblem = message
            case false?:
                self.retry(url, summary: summary)
            }
            self.refreshCount()
        }
    }
}
