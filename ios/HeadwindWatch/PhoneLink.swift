import Foundation
import Observation
import WatchConnectivity

/// Watch end of the iPhone link. Finished rides go to the phone with transferFile, which the system queues and
/// delivers whenever the phone is reachable, even hours later, so riding without the phone is fine.
/// The phone sends back the server's units, whether it's paired and the rider's bikes.
@MainActor
@Observable
final class PhoneLink: NSObject {
    private(set) var units = Units(system: "metric")
    private(set) var phonePaired = true
    private(set) var bikes: [Bike] = []
    /// Rides in the outbox: not yet confirmed delivered to the phone.
    private(set) var waitingToSend = 0
    /// Why rides are stuck in the outbox (e.g. Headwind isn't installed on the iPhone); nil while sending normally.
    private(set) var sendProblem: String?
    /// Failed attempts per outbox file, for backing off, and the files waiting out a backoff.
    @ObservationIgnored private var failures: [String: Int] = [:]
    @ObservationIgnored private var retrying: Set<String> = []

    private let outbox: URL = {
        let dir = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        let url = dir.appending(path: "Outbox", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()

    override init() {
        super.init()
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func send(gpx: Data, summary: RideSummary) throws(AppError) {
        let file = outbox.appending(path: "\(UUID().uuidString).gpx")
        do {
            try gpx.write(to: file, options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
        // Kept so the ride can be sent again on a later launch; without it the phone falls back to the GPX alone.
        try? JSONEncoder().encode(summary).write(to: sidecar(file), options: .atomic)
        transfer(file, summary: summary)
    }

    private func transfer(_ file: URL, summary: RideSummary?) {
        var metadata = summary?.dictionary ?? [:]
        metadata[WatchLink.kindKey] = WatchLink.rideKind
        WCSession.default.transferFile(file, metadata: metadata)
        refreshCount()
    }

    /// Queue every outbox ride the system isn't already sending: ones given up on after a permanent error, or
    /// left waiting out a backoff when the app was last closed.
    private func resendOutbox() {
        let queued = Set(WCSession.default.outstandingFileTransfers.map { $0.file.fileURL.lastPathComponent })
        for file in outboxRides() where !queued.contains(file.lastPathComponent) && !retrying.contains(file.lastPathComponent) {
            let summary = (try? Data(contentsOf: sidecar(file))).flatMap { try? JSONDecoder().decode(RideSummary.self, from: $0) }
            transfer(file, summary: summary)
        }
    }

    /// Try a failed transfer again after 15 s, doubling each time up to 30 min, so a phone that keeps refusing
    /// doesn't keep the radio busy.
    private func retry(_ file: URL, summary: RideSummary?) {
        let name = file.lastPathComponent
        let attempt = failures[name, default: 0] + 1
        failures[name] = attempt
        let delay = min(15 * Double(1 << min(attempt - 1, 7)), 30 * 60)
        retrying.insert(name)
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard let self else { return }
            self.retrying.remove(name)
            guard FileManager.default.fileExists(atPath: file.path) else { return }
            self.transfer(file, summary: summary)
        }
    }

    private func delivered(_ file: URL) {
        try? FileManager.default.removeItem(at: file)
        try? FileManager.default.removeItem(at: sidecar(file))
        failures[file.lastPathComponent] = nil
        sendProblem = nil
    }

    private func outboxRides() -> [URL] {
        let files = (try? FileManager.default.contentsOfDirectory(at: outbox, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.pathExtension == "gpx" }
    }

    private func sidecar(_ file: URL) -> URL { file.deletingPathExtension().appendingPathExtension("json") }

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
