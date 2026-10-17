import Foundation

/// The headline numbers of a finished ride. Travels with the GPX from the Watch to the iPhone (as
/// WatchConnectivity file metadata) and is kept in the iPhone's list of recordings.
struct RideSummary: Codable, Equatable, Sendable {
    var start: Date
    var distance: Double
    var movingTime: TimeInterval
    var elapsedTime: TimeInterval
    var elevationGain: Double
    var averageHeartRate: Int?

    init(start: Date, distance: Double, movingTime: TimeInterval, elapsedTime: TimeInterval, elevationGain: Double, averageHeartRate: Int? = nil) {
        self.start = start
        self.distance = distance
        self.movingTime = movingTime
        self.elapsedTime = elapsedTime
        self.elevationGain = elevationGain
        self.averageHeartRate = averageHeartRate
    }

    init(start: Date, tracker: RideTracker, elapsed: TimeInterval) {
        self.init(start: start, distance: tracker.distance, movingTime: tracker.movingTime, elapsedTime: elapsed,
                  elevationGain: tracker.elevationGain, averageHeartRate: tracker.averageHeartRate)
    }

    // WatchConnectivity metadata must be property-list types, so round-trip through a plain dictionary.
    var dictionary: [String: Any] {
        var d: [String: Any] = ["start": start.timeIntervalSince1970, "distance": distance, "movingTime": movingTime,
                                "elapsedTime": elapsedTime, "elevationGain": elevationGain]
        if let averageHeartRate { d["averageHeartRate"] = averageHeartRate }
        return d
    }

    init?(dictionary d: [String: Any]) {
        guard let start = d["start"] as? Double, let distance = d["distance"] as? Double else { return nil }
        self.init(start: Date(timeIntervalSince1970: start), distance: distance,
                  movingTime: d["movingTime"] as? Double ?? 0, elapsedTime: d["elapsedTime"] as? Double ?? 0,
                  elevationGain: d["elevationGain"] as? Double ?? 0, averageHeartRate: d["averageHeartRate"] as? Int)
    }
}

/// Keys shared by both ends of the WatchConnectivity link.
enum WatchLink {
    /// iPhone → Watch application context: "metric" or "imperial", from the server's /ping.
    static let unitsKey = "units"
    /// iPhone → Watch application context: whether the iPhone is paired with a server (the Watch warns if not).
    static let pairedKey = "paired"
    /// Watch → iPhone file metadata: marks a transferred file as a recorded ride.
    static let kindKey = "kind"
    static let rideKind = "ride"
}
