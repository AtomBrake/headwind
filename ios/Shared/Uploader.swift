import Foundation

/// POST /api/v1/activities reply (routes/api_v1.py post_activity): {status 'created'|'exists', created, id, duplicate}.
struct UploadReply: Decodable, Sendable {
    var status: String
    var serverId: String?
    /// "created"; anything else ("exists") was already there.
    var isNew: Bool { status == "created" }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decode(String.self, forKey: .status)
        // The id is informational: accept a string or a number, and never fail the whole reply over it.
        serverId = (try? c.decode(String.self, forKey: .id)) ?? (try? c.decode(Int.self, forKey: .id)).map(String.init)
    }

    private enum CodingKeys: String, CodingKey { case status, id }
}

/// Where a finished recording goes, and sending it there. Shared by the iPhone's upload queue (RideStore) and the Watch's direct upload, so both
/// send the same thing with the same client_id and the server keeps one copy.
enum Uploader {
    /// A recording with a track: to POST /api/v1/activities (routes/api_v1.py post_activity) with its sport and the recording's id as
    /// client_id, so a retry after a dropped reply finds the first upload, and a ride with the chosen bike. Timed-only sessions don't come
    /// here: see `sessionBody`.
    static func destination(summary s: RideSummary, id: UUID, name: String, clientID: String? = nil) -> (path: String, fields: [String: String]) {
        let bike = s.sport.isRide ? s.bikeId.map { ["bike_id": String($0)] } ?? [:] : [:]
        var fields = ["sport": s.sport.serverSport, "name": name, "client_id": clientID ?? id.uuidString, "source": "ios"]
        if let kcal = s.calories, kcal > 0 { fields["calories"] = String(Int(kcal.rounded())) }
        return ("activities", fields.merging(bike) { $1 })
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
        try await client.send(request(summary: summary, id: id, name: name, gpx: gpx, clientID: clientID, with: client), as: UploadReply.self)
    }

    /// The request `upload` sends, for the Watch to hand to a background session; its reply is read with `APIClient.reply`.
    static func request(summary: RideSummary, id: UUID, name: String, gpx: Data?, clientID: String? = nil,
                        with client: APIClient) throws(AppError) -> URLRequest {
        if let gpx {
            let (path, fields) = destination(summary: summary, id: id, name: name, clientID: clientID)
            return client.uploadRequest(path, file: gpx, filename: "\(name).gpx", mimeType: "application/gpx+xml", fields: fields)
        }
        guard summary.movingTime >= RideSummary.minimumSession else { throw .sessionTooShort }
        return try client.postRequest("activities", json: sessionBody(summary: summary, id: id, name: name, clientID: clientID))
    }
}

/// Where an activity is in the phone API, whatever its sport (routes/api_v1.py activity_detail), and its page on the web.
enum ActivityPath {
    /// Every activity, a page at a time.
    static let list = "activities"

    /// One activity; the paths under it add "/photos", "/bike" and so on.
    static func of(_ id: String) -> String { "activities/\(id)" }

    /// Its page on the web, relative to the server.
    static func page(_ id: String) -> String { "activities/\(id)" }
}
