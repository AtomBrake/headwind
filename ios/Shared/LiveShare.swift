import CoreLocation
import Foundation

/// Body of POST /api/v1/live (services/live.py clean()): the recorder's reading, sent while it records and once more, idle, when it stops.
/// `recording` is the recording's id (the client_id its upload sends), so a live tracking link takes only its own recording's readings,
/// and the idle reading ends that link (services/live_share.py).
struct LiveUpdate: Encodable, Sendable {
    var state: String
    var recording: String?
    var lat: Double?
    var lng: Double?
    var speed_mps: Double
    var distance_m: Double
    var elapsed_s: Int
    var alt_m: Double?
    var accuracy_m: Double?
    var sport: String
    var battery_pct: Int?

    /// The reading that ends a recording (and its link).
    static func idle(recording: UUID?, sport: Sport, distance: Double, elapsed: TimeInterval, battery: Int?) -> LiveUpdate {
        LiveUpdate(state: "idle", recording: recording?.uuidString, speed_mps: 0, distance_m: distance, elapsed_s: Int(elapsed),
                   sport: sport.rawValue, battery_pct: battery)
    }
}

/// How often a recorder posts /api/v1/live.
enum LiveCadence {
    /// The phone, for Home Assistant: a position every 15 s is plenty.
    static let phone: TimeInterval = 15
    /// The phone while a link is shared, unless the server says otherwise (`send_every_s`): the page moves along with the rider.
    static let sharing: TimeInterval = 5
    /// The Watch posting for itself: every 30 s, to spare its battery and cellular.
    static let watch: TimeInterval = 30

    /// The phone's gap between posts: the server's `send_every_s` while sharing (5 s, and never under a second), 15 s otherwise.
    static func phone(sharing: Bool, sendEvery: Double? = nil) -> TimeInterval {
        guard sharing else { return phone }
        guard let sendEvery, sendEvery.isFinite, sendEvery > 0 else { return Self.sharing }
        return max(1, min(sendEvery, phone))
    }

    /// Whether a post is due: forced (Start, Stop), or `interval` since the last one.
    static func due(last: Date, now: Date = .now, interval: TimeInterval, force: Bool = false) -> Bool {
        force || now.timeIntervalSince(last) >= interval
    }
}

/// Body of POST /api/v1/live/share: start a link for this recording, with what was recorded before sharing began.
struct LiveShareStart: Encodable, Sendable {
    var recording: String
    var sport: String
    /// [[lat, lng, epoch seconds], ...]; left out when sharing starts with the recording.
    var track: [[Double]]?
}

extension LiveShareStart {
    /// The request for a recording: with the track so far, thinned, when sharing starts after it (none when there's none yet).
    static func make(recording: UUID, sport: Sport, track: [RidePoint]) -> LiveShareStart {
        let thinned = LiveTrack.thinned(track)
        return LiveShareStart(recording: recording.uuidString, sport: sport.rawValue, track: thinned.isEmpty ? nil : thinned)
    }
}

/// Watch → iPhone user info (`WatchLink.liveLinkKey`): a link the Watch started for its recording, for the phone to offer in a
/// notification and the share sheet, or word that the recording has ended, so the phone shows the link as finished.
struct LiveLinkMessage: Equatable, Sendable {
    var recording: String
    var url: URL?
    /// Epoch seconds.
    var expiresAt: Double?
    /// The Sport rawValue.
    var sport: String?
    var ended = false

    static func started(recording: UUID, reply: LiveShareReply, sport: Sport) -> LiveLinkMessage {
        LiveLinkMessage(recording: recording.uuidString, url: reply.url, expiresAt: reply.expiresAt, sport: sport.rawValue)
    }

    static func ended(recording: UUID) -> LiveLinkMessage {
        LiveLinkMessage(recording: recording.uuidString, ended: true)
    }

    var dictionary: [String: Any] {
        var d: [String: Any] = ["recording": recording, "ended": ended]
        if let url { d["url"] = url.absoluteString }
        if let expiresAt { d["expires"] = expiresAt }
        if let sport { d["sport"] = sport }
        return d
    }

    /// Nil for anything that isn't one: no recording, or a link with no address.
    init?(dictionary d: [String: Any]) {
        guard let recording = d["recording"] as? String, !recording.isEmpty else { return nil }
        let ended = d["ended"] as? Bool ?? false
        let url = (d["url"] as? String).flatMap(URL.init(string:))
        guard ended || url != nil else { return nil }
        self.init(recording: recording, url: url, expiresAt: d["expires"] as? Double, sport: d["sport"] as? String, ended: ended)
    }

    init(recording: String, url: URL? = nil, expiresAt: Double? = nil, sport: String? = nil, ended: Bool = false) {
        self.recording = recording
        self.url = url
        self.expiresAt = expiresAt
        self.sport = sport
        self.ended = ended
    }
}

/// Body of DELETE /api/v1/live/share.
struct LiveShareStop: Encodable, Sendable {
    var recording: String
}

/// POST /api/v1/live/share reply: the link, and how often to post while it runs.
struct LiveShareReply: Decodable, Sendable, Equatable {
    var id: Int
    var url: URL
    var recording: String
    /// Epoch seconds.
    var expiresAt: Double
    var ended: Bool
    var sendEveryS: Double?
    var created: Bool?
}

/// DELETE /api/v1/live/share reply.
struct LiveShareStopped: Decodable, Sendable {
    var stopped: Int
}

/// A 409 from POST /api/v1/live/share: the server has no outside https address anyone could open the link on. `error` is fit to show.
struct LiveShareRefusal: Decodable, Sendable, Equatable {
    var error: String
    var settingsUrl: String?

    /// The page to fix it on, on the paired server.
    func settings(on server: URL) -> URL? {
        guard let path = settingsUrl, !path.isEmpty else { return nil }
        return URL(string: path, relativeTo: server)?.absoluteURL
    }
}

/// What can come of asking for a link.
enum LiveShareOutcome: Sendable, Equatable {
    case shared(LiveShareReply)
    case refused(LiveShareRefusal)
}

/// The track recorded before sharing began, thinned for POST /api/v1/live/share as the server thins what it keeps (services/live_share.py
/// _add_point): a point when THIN_S seconds or THIN_M metres have passed since the last kept one, never one under MIN_MOVE_M from it, and at
/// most `limit` of them (the server takes the last 5,000), spread evenly over the track with its last point kept.
enum LiveTrack {
    static let thinSeconds: TimeInterval = 10
    static let thinMetres = 25.0
    static let minMove = 5.0
    static let limit = 5_000

    static func thinned(_ points: [RidePoint], limit: Int = limit) -> [[Double]] {
        var kept: [RidePoint] = []
        for p in points {
            if let last = kept.last {
                guard p.time > last.time else { continue }
                let moved = last.distance(to: p)
                if moved < minMove || (moved < thinMetres && p.time.timeIntervalSince(last.time) < thinSeconds) { continue }
            }
            kept.append(p)
        }
        if kept.count > limit, limit > 1 {
            // Every nth, ending on the last point so the link's track reaches where the rider is.
            let step = Double(kept.count - 1) / Double(limit - 1)
            kept = (0..<limit).map { kept[Int((Double($0) * step).rounded())] }
        }
        return kept.map { [$0.lat, $0.lon, ($0.time.timeIntervalSince1970 * 1000).rounded() / 1000] }
    }
}

/// The live tracking link's calls, for the phone and the Watch alike.
extension APIClient {
    /// Start a link for the recording, or get the one it already has (the same link, so this is safe to call again). A 409 comes back as
    /// `.refused` with the server's reason; any other failure throws.
    func startLiveShare(_ body: LiveShareStart) async throws(AppError) -> LiveShareOutcome {
        let (data, http) = try await perform(postRequest("live/share", json: body))
        if http.statusCode == 409, let refusal = try? JSONDecoder.headwind.decode(LiveShareRefusal.self, from: data) {
            return .refused(refusal)
        }
        return .shared(try Self.reply(data, status: http.statusCode, as: LiveShareReply.self))
    }

    /// Stop sharing the recording: its link ends at once. Returns how many links were stopped.
    @discardableResult
    func stopLiveShare(recording: String) async throws(AppError) -> Int {
        try await send(jsonRequest("live/share", method: "DELETE", json: LiveShareStop(recording: recording)), as: LiveShareStopped.self).stopped
    }
}
