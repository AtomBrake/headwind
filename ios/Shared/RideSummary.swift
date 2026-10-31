import Foundation

/// The headline numbers of a finished recording, with its sport and bike. Travels with the GPX from the Watch to the
/// iPhone (as WatchConnectivity file metadata) and is kept in the iPhone's list of recordings.
struct RideSummary: Codable, Equatable, Sendable {
    var start: Date
    var distance: Double
    var movingTime: TimeInterval
    var elapsedTime: TimeInterval
    var elevationGain: Double
    var averageHeartRate: Int?
    var sport: Sport
    /// The bike chosen for a ride (Bike.id on the server); nil leaves it to the server's default.
    var bikeId: Int?

    init(start: Date, distance: Double, movingTime: TimeInterval, elapsedTime: TimeInterval, elevationGain: Double,
         averageHeartRate: Int? = nil, sport: Sport = .ride, bikeId: Int? = nil) {
        self.start = start
        self.distance = distance
        self.movingTime = movingTime
        self.elapsedTime = elapsedTime
        self.elevationGain = elevationGain
        self.averageHeartRate = averageHeartRate
        self.sport = sport
        self.bikeId = sport.isRide ? bikeId : nil
    }

    init(start: Date, tracker: RideTracker, elapsed: TimeInterval, sport: Sport = .ride, bikeId: Int? = nil) {
        self.init(start: start, distance: tracker.distance, movingTime: tracker.movingTime, elapsedTime: elapsed,
                  elevationGain: tracker.elevationGain, averageHeartRate: tracker.averageHeartRate, sport: sport, bikeId: bikeId)
    }

    /// Recordings saved before the sport was chosen have none: they're rides.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(start: try c.decode(Date.self, forKey: .start), distance: try c.decode(Double.self, forKey: .distance),
                  movingTime: try c.decode(Double.self, forKey: .movingTime), elapsedTime: try c.decode(Double.self, forKey: .elapsedTime),
                  elevationGain: try c.decode(Double.self, forKey: .elevationGain),
                  averageHeartRate: try c.decodeIfPresent(Int.self, forKey: .averageHeartRate),
                  sport: Sport(stored: try? c.decodeIfPresent(String.self, forKey: .sport)),
                  bikeId: try? c.decodeIfPresent(Int.self, forKey: .bikeId))
    }

    // WatchConnectivity metadata must be property-list types, so round-trip through a plain dictionary.
    var dictionary: [String: Any] {
        var d: [String: Any] = ["start": start.timeIntervalSince1970, "distance": distance, "movingTime": movingTime,
                                "elapsedTime": elapsedTime, "elevationGain": elevationGain, "sport": sport.rawValue]
        if let averageHeartRate { d["averageHeartRate"] = averageHeartRate }
        if let bikeId { d["bikeId"] = bikeId }
        return d
    }

    init?(dictionary d: [String: Any]) {
        guard let start = d["start"] as? Double, let distance = d["distance"] as? Double else { return nil }
        self.init(start: Date(timeIntervalSince1970: start), distance: distance,
                  movingTime: d["movingTime"] as? Double ?? 0, elapsedTime: d["elapsedTime"] as? Double ?? 0,
                  elevationGain: d["elevationGain"] as? Double ?? 0, averageHeartRate: d["averageHeartRate"] as? Int,
                  sport: Sport(stored: d["sport"] as? String), bikeId: d["bikeId"] as? Int)
    }
}

/// Keys shared by both ends of the WatchConnectivity link.
enum WatchLink {
    /// iPhone → Watch application context: "metric" or "imperial", from the server's /ping.
    static let unitsKey = "units"
    /// iPhone → Watch application context: whether the iPhone is paired with a server (the Watch warns if not).
    static let pairedKey = "paired"
    /// iPhone → Watch application context: the rider's bikes (Bike.dictionary), for the Watch's bike picker.
    static let bikesKey = "bikes"
    /// Watch → iPhone file metadata: marks a transferred file as a recorded ride.
    static let kindKey = "kind"
    static let rideKind = "ride"
}
