import Foundation
import Observation

/// A live tracking link for the recording in progress: a page anyone the rider sends it to opens in a browser, with no account, to see where
/// they are, the track so far and their figures (services/live_share.py on the server).
///
/// Sharing starts at Start when the Record screen's switch is on (its default is in Settings), or when it's switched on mid-recording, with
/// the track so far. The server answers with the link, which goes to the share sheet. While the link runs the recorder posts every
/// `send_every_s` (5 s) instead of every 15 s. The recorder's idle post at Stop ends the link, which then works for an hour more, and the link
/// stays on the Record screen until then, to send again, copy or stop. Stop sharing ends it at once (DELETE).
///
/// A refusal (409: the server has no outside https address) is shown with the server's reason and its Settings page. The recording goes on
/// without the link.
///
/// A Watch recording's link is started by the Watch, which has no share sheet, and handed over (WatchBridge, `LiveLinkMessage`): it's kept
/// here like the phone's own, announced in a notification (LiveLinkNotifier) whose tap opens the share sheet, and shown as finished when
/// the Watch says its recording has ended.
@MainActor
@Observable
final class LiveShareController {
    /// A link this phone (or its Watch) started, kept across launches until it expires.
    struct Link: Codable, Equatable, Sendable {
        var recording: String
        var url: URL
        var expiresAt: Date
        /// The recording has finished: the link shows it as finished, and ends an hour after.
        var ended = false
        /// The Sport rawValue, for the share sheet's words; nil for the phone's own (the recorder knows it).
        var sport: String?
        /// Started by the Watch for its recording.
        var fromWatch: Bool?
    }

    /// A link to show in the share sheet.
    struct Outgoing: Identifiable, Equatable {
        var url: URL
        var sport: Sport
        var id: URL { url }
    }

    /// Why a link couldn't be started, and where to fix it.
    struct Problem: Identifiable, Equatable {
        var message: String
        var settings: URL?
        var id: String { message }
    }

    /// Settings: share a link at every Start.
    var shareByDefault: Bool {
        didSet {
            defaults.set(shareByDefault, forKey: Self.defaultKey)
            wanted = shareByDefault             // read only at Start, so changing it mid-recording changes the next one
            if shareByDefault { notifier?.askPermission() }     // the Watch's links arrive as notifications
        }
    }
    /// The Record screen's switch before Start. Back to the default after each recording.
    var wanted: Bool
    private(set) var link: Link? {
        didSet { save() }
    }
    /// Asking the server for a link, or to stop one.
    private(set) var busy = false
    /// The link to put in the share sheet now.
    var outgoing: Outgoing?
    var problem: Problem?

    @ObservationIgnored private let defaults: UserDefaults
    /// Set by the app: the notification for a link from the Watch. Nil in tests and previews.
    @ObservationIgnored var notifier: LiveLinkNotifier?
    private static let defaultKey = "live-share-default", linkKey = "live-share-link"
    /// How long a link works after its recording ends (services/live_share.AFTER_END_S).
    static let afterEnd: TimeInterval = 3600

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let on = defaults.bool(forKey: Self.defaultKey)
        shareByDefault = on
        wanted = on
        link = defaults.data(forKey: Self.linkKey).flatMap { try? JSONDecoder().decode(Link.self, from: $0) }
        if let link, link.expiresAt <= .now { self.link = nil }
    }

    /// The link still working (it may be for a finished recording), or nil.
    func current(at now: Date = .now) -> Link? {
        guard let link, link.expiresAt > now else { return nil }
        return link
    }

    /// Whether this recording's link is running.
    func isSharing(_ recording: UUID?) -> Bool {
        guard let recording, let link = current() else { return false }
        return link.recording == recording.uuidString && !link.ended
    }

    /// The share request for the recorder's recording: with the track so far, thinned, when sharing starts after it.
    nonisolated static func request(recording: UUID, sport: Sport, track: [RidePoint]) -> LiveShareStart {
        LiveShareStart.make(recording: recording, sport: sport, track: track)
    }

    /// Start sharing the recording in progress and offer the link in the share sheet.
    func start(recorder: PhoneRideRecorder, pairing: Pairing?) async {
        guard let id = recorder.recordingID, recorder.sport.usesGPS, !busy else { return }
        guard let pairing else {
            problem = Problem(message: AppError.notPaired.localizedDescription, settings: nil)
            return
        }
        busy = true
        defer { busy = false }
        let sport = recorder.sport
        let client = APIClient(pairing: pairing)
        let outcome: LiveShareOutcome
        do throws(AppError) {
            outcome = try await client.startLiveShare(Self.request(recording: id, sport: sport, track: recorder.tracker.points))
        } catch {
            wanted = false
            problem = Problem(message: "Couldn't start the live link: \(error.localizedDescription) The recording goes on.", settings: nil)
            return
        }
        switch outcome {
        case .refused(let refusal):
            wanted = false
            problem = Problem(message: refusal.error, settings: refusal.settings(on: pairing.server))
        case .shared(let reply):
            guard recorder.recordingID == id else {
                // Finished while the server answered: its idle post may have come first, so end the link rather than leave it running.
                _ = try? await client.stopLiveShare(recording: id.uuidString)
                return
            }
            link = Link(recording: id.uuidString, url: reply.url, expiresAt: Date(timeIntervalSince1970: reply.expiresAt), ended: reply.ended)
            recorder.sharingEvery = reply.sendEveryS ?? LiveCadence.sharing
            outgoing = Outgoing(url: reply.url, sport: sport)
        }
    }

    /// Stop sharing: the link ends at once for everyone who has it.
    func stop(recorder: PhoneRideRecorder, pairing: Pairing?) async {
        guard !busy else { return }
        guard let link = current() else {
            self.link = nil
            return
        }
        guard let pairing else {
            problem = Problem(message: AppError.notPaired.localizedDescription, settings: nil)
            return
        }
        busy = true
        defer { busy = false }
        do throws(AppError) {
            try await APIClient(pairing: pairing).stopLiveShare(recording: link.recording)
            self.link = nil
            notifier?.withdraw(recording: link.recording)
            if recorder.recordingID?.uuidString == link.recording { recorder.sharingEvery = nil }
            wanted = false
        } catch {
            problem = Problem(message: "Couldn't stop the live link: \(error.localizedDescription) Try again, or stop it on the server.",
                              settings: nil)
        }
    }

    /// The recorder has finished (or discarded) this recording and posted its idle reading: the link now ends within the hour.
    func recordingEnded(_ recording: UUID) {
        ended(recording.uuidString)
        wanted = shareByDefault
    }

    private func ended(_ recording: String) {
        guard var l = link, l.recording == recording, !l.ended else { return }
        l.ended = true
        l.expiresAt = min(l.expiresAt, Date().addingTimeInterval(Self.afterEnd))
        link = l
    }

    /// A link the Watch started for its recording, or word that the recording has ended. A new link is kept and announced; the share
    /// sheet opens when the notification is tapped (`offer`). One sent again (the Watch's message delivered twice) isn't announced again.
    func adopt(fromWatch message: LiveLinkMessage) {
        if message.ended {
            ended(message.recording)
            notifier?.withdraw(recording: message.recording)
            return
        }
        guard let url = message.url, link?.recording != message.recording else { return }
        let expires = message.expiresAt.map(Date.init(timeIntervalSince1970:)) ?? Date().addingTimeInterval(6 * 3600)
        guard expires > .now else { return }
        let new = Link(recording: message.recording, url: url, expiresAt: expires, sport: message.sport, fromWatch: true)
        link = new
        notifier?.askPermission()
        notifier?.announce(new)
    }

    /// Open the share sheet with this recording's link, if it still works (the notification was tapped).
    func offer(recording: String) {
        guard let link = current(), link.recording == recording else { return }
        outgoing = Outgoing(url: link.url, sport: Sport(stored: link.sport))
    }

    private func save() {
        if let link, let data = try? JSONEncoder().encode(link) {
            defaults.set(data, forKey: Self.linkKey)
        } else {
            defaults.removeObject(forKey: Self.linkKey)
        }
    }
}
