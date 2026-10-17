import Foundation
import Observation
import WatchConnectivity

/// Watch end of the iPhone link. Finished rides go to the phone with transferFile, which the system queues and
/// delivers whenever the phone is reachable, even hours later, so riding without the phone is fine.
/// The phone sends back the server's units and whether it's paired.
@MainActor
@Observable
final class PhoneLink: NSObject {
    private(set) var units = Units(system: "metric")
    private(set) var phonePaired = true
    /// Rides handed to the system but not yet confirmed delivered to the phone.
    private(set) var waitingToSend = 0

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
        transfer(file, summary: summary)
    }

    private func transfer(_ file: URL, summary: RideSummary) {
        var metadata = summary.dictionary
        metadata[WatchLink.kindKey] = WatchLink.rideKind
        WCSession.default.transferFile(file, metadata: metadata)
        refreshCount()
    }

    private func refreshCount() {
        waitingToSend = WCSession.default.outstandingFileTransfers.filter { $0.isTransferring || !$0.progress.isFinished }.count
    }

    private func apply(units system: String?, paired: Bool?) {
        if let system { units = Units(system: system) }
        if let paired { phonePaired = paired }
    }
}

extension PhoneLink: WCSessionDelegate {
    nonisolated func session(_ session: WCSession, activationDidCompleteWith state: WCSessionActivationState, error: Error?) {
        let context = session.receivedApplicationContext
        let units = context[WatchLink.unitsKey] as? String, paired = context[WatchLink.pairedKey] as? Bool
        Task { @MainActor in
            self.apply(units: units, paired: paired)
            self.refreshCount()
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveApplicationContext context: [String: Any]) {
        let units = context[WatchLink.unitsKey] as? String, paired = context[WatchLink.pairedKey] as? Bool
        Task { @MainActor in self.apply(units: units, paired: paired) }
    }

    nonisolated func session(_ session: WCSession, didFinish fileTransfer: WCSessionFileTransfer, error: Error?) {
        let url = fileTransfer.file.fileURL
        let failed = error != nil
        let summary = fileTransfer.file.metadata.flatMap(RideSummary.init(dictionary:))
        Task { @MainActor in
            if failed, let summary {
                // Hand it to the system again; it keeps retrying until the phone takes it.
                self.transfer(url, summary: summary)
            } else {
                try? FileManager.default.removeItem(at: url)
            }
            self.refreshCount()
        }
    }
}
