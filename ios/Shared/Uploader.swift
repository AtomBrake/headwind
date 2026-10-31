import Foundation

/// POST /api/v1/rides reply (routes/api_v1.py upload_ride), /workouts (post_workout), whose activity is under `workout`, or /activities
/// (post_activity), whose id and kind are at the top.
struct UploadReply: Decodable, Sendable {
    var status: String
    var serverId: String?
    /// 'ride' or 'workout' when the server said; otherwise worked out from the sport.
    var kind: String?
    /// /rides says "imported", /workouts and /activities "created"; anything else was already there.
    var isNew: Bool { status == "imported" || status == "created" }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(String.self, forKey: .status)
        kind = try? c.decodeIfPresent(String.self, forKey: .kind)
        let nested = (try? c.decodeIfPresent(Activity.self, forKey: .ride)) ?? (try? c.decodeIfPresent(Activity.self, forKey: .workout))
        serverId = nested?.id ?? Self.flexibleID(c, .id)
    }

    /// The id is informational: accept a string or a number, and never fail the whole reply over it.
    private static func flexibleID<K: CodingKey>(_ c: KeyedDecodingContainer<K>, _ key: K) -> String? {
        (try? c.decode(String.self, forKey: key)) ?? (try? c.decode(Int.self, forKey: key)).map(String.init)
    }

    private struct Activity: Decodable, Sendable {
        var id: String?
        init(from decoder: Decoder) throws {
            id = UploadReply.flexibleID(try decoder.container(keyedBy: CodingKeys.self), .id)
        }
    }

    private enum CodingKeys: String, CodingKey { case status, kind, ride, workout, id }
}

/// Where a finished recording goes, and sending it there. Shared by the iPhone's upload queue (RideStore) and the Watch's direct upload, so both
/// send the same thing with the same client_id and the server keeps one copy.
enum Uploader {
    /// GPS rides to /rides with the chosen bike (idempotent by content); other GPS sports to /workouts with their sport and the recording's id as
    /// client_id, so a retry after a dropped reply finds the first upload. Timed-only sessions don't come here: see `sessionBody`.
    static func destination(summary s: RideSummary, id: UUID, name: String, clientID: String? = nil) -> (path: String, fields: [String: String]) {
        if s.sport.isRide {
            return ("rides", s.bikeId.map { ["bike_id": String($0)] } ?? [:])
        }
        var fields = ["sport": s.sport.serverSport, "name": name, "client_id": clientID ?? id.uuidString, "source": "ios"]
        if let kcal = s.calories, kcal > 0 { fields["calories"] = String(Int(kcal.rounded())) }
        return ("workouts", fields)
    }

    /// Body of POST /api/v1/activities for a timed-only session (services/manual_activity.create).
    struct SessionBody: Encodable, Sendable {
        var sport: String
        var start: String
        var duration_s: Int
        var distance_m: Double?
        var calories: Int?
        var avg_hr: Int?
        var name: String
        var client_id: String
        var source = "ios"
        var bike_id: Int?
    }

    static func sessionBody(summary s: RideSummary, id: UUID, name: String, clientID: String? = nil) -> SessionBody {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        iso.timeZone = .current     // the phone's own offset: the server keeps the wall-clock time where it happened
        return SessionBody(sport: s.sport.serverSport, start: iso.string(from: s.start), duration_s: Int(s.movingTime.rounded()),
                           distance_m: s.sport.hasDistance ? s.distance : nil, calories: s.calories.map { Int($0.rounded()) },
                           avg_hr: s.averageHeartRate, name: name, client_id: clientID ?? id.uuidString, bike_id: s.bikeId)
    }

    /// Send one recording: its GPX when it has a track, its summary alone otherwise (a timed-only session, or a workout from another app
    /// that came without a route). `clientID` replaces the id as the server's client_id (Apple Health's workouts are `ah_<uuid>`).
    static func upload(summary: RideSummary, id: UUID, name: String, gpx: Data?, clientID: String? = nil,
                       with client: APIClient) async throws(AppError) -> UploadReply {
        if let gpx {
            let (path, fields) = destination(summary: summary, id: id, name: name, clientID: clientID)
            return try await client.upload(path, file: gpx, filename: "\(name).gpx", mimeType: "application/gpx+xml", fields: fields,
                                           as: UploadReply.self)
        }
        guard summary.movingTime >= RideSummary.minimumSession else { throw .sessionTooShort }
        return try await client.post("activities", json: sessionBody(summary: summary, id: id, name: name, clientID: clientID), as: UploadReply.self)
    }

    /// The server's kind for a recording ('ride' or 'workout'), for the paths that take one (photos, bike, delete).
    static func kind(of summary: RideSummary, reply: String? = nil) -> String {
        reply ?? (summary.sport.isRide ? "ride" : "workout")
    }
}
