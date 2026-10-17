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

    init(store: RideStore) {
        self.store = store
        super.init()
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func updateWatch(units: String?, paired: Bool) {
        guard WCSession.isSupported(), WCSession.default.activationState == .activated,
              WCSession.default.isPaired, WCSession.default.isWatchAppInstalled else { return }
        try? WCSession.default.updateApplicationContext([WatchLink.unitsKey: units ?? "metric", WatchLink.pairedKey: paired])
    }

    private func adopt(file: URL, summary: RideSummary) {
        do throws(AppError) {
            try store.adopt(file: file, summary: summary, source: .watch)
            lastError = nil
            onRideReceived?()
        } catch {
            lastError = error
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
        guard file.metadata?[WatchLink.kindKey] as? String == WatchLink.rideKind,
              let summary = file.metadata.flatMap(RideSummary.init(dictionary:)) else { return }
        // The system deletes the file when this method returns, so move it somewhere safe first, synchronously.
        let holding = FileManager.default.temporaryDirectory.appending(path: "watch-\(UUID().uuidString).gpx")
        do {
            try FileManager.default.moveItem(at: file.fileURL, to: holding)
        } catch {
            return
        }
        Task { @MainActor in self.adopt(file: holding, summary: summary) }
    }
}
