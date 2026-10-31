import Foundation

/// What a recording is, chosen before Start and locked once recording. The raw values are the server's sport names
/// (services/sports.py RIDES and ON_FOOT); indoor rides aren't recorded with GPS, so VirtualRide isn't offered.
enum Sport: String, Codable, CaseIterable, Identifiable, Sendable {
    case ride = "Ride"
    case ebike = "EBikeRide"
    case run = "Run"
    case walk = "Walk"
    case hike = "Hike"

    var id: Self { self }

    var title: String {
        switch self {
        case .ride: "Ride"
        case .ebike: "E-bike ride"
        case .run: "Run"
        case .walk: "Walk"
        case .hike: "Hike"
        }
    }

    /// The end of the activity's name: "Morning Ride", "Evening E-bike Ride", "Night Run".
    var nameWord: String {
        switch self {
        case .ride: "Ride"
        case .ebike: "E-bike Ride"
        case .run: "Run"
        case .walk: "Walk"
        case .hike: "Hike"
        }
    }

    var systemImage: String {
        switch self {
        case .ride: "bicycle"
        case .ebike: "bolt.fill"
        case .run: "figure.run"
        case .walk: "figure.walk"
        case .hike: "figure.hiking"
        }
    }

    /// Rides go to POST /api/v1/rides and have a bike; the rest go to /api/v1/workouts.
    var isRide: Bool { self == .ride || self == .ebike }

    /// The GPX <type>, which services/parser.py _SPORT_MAP turns back into this sport.
    var gpxType: String {
        switch self {
        case .ride: "cycling"
        case .ebike: "ebike"
        case .run: "running"
        case .walk: "walking"
        case .hike: "hiking"
        }
    }

    /// Unknown or missing values (an older app's recording, a sport this build doesn't know) are rides, as every recording used to be.
    init(stored raw: String?) {
        self = raw.flatMap(Sport.init(rawValue:)) ?? .ride
    }
}

/// One of the rider's bikes, from /ping (routes/api_v1.py _bikes). The phone keeps the last list with the ping info, so the
/// picker works offline, and passes it on to the Watch.
struct Bike: Codable, Equatable, Identifiable, Sendable {
    var id: Int
    var name: String
    var kind: String?
    var isDefault: Bool?

    var isEbike: Bool { kind == "ebike" }

    /// The bike to record on: the one last chosen if it's still in the list, else the server's default, else none.
    static func pick(_ chosen: Int?, from bikes: [Bike]) -> Int? {
        if let chosen, bikes.contains(where: { $0.id == chosen }) { return chosen }
        return bikes.first { $0.isDefault == true }?.id
    }

    // WatchConnectivity application context must be property-list types.
    var dictionary: [String: Any] {
        var d: [String: Any] = ["id": id, "name": name, "default": isDefault ?? false]
        if let kind { d["kind"] = kind }
        return d
    }

    init(id: Int, name: String, kind: String? = nil, isDefault: Bool? = nil) {
        self.id = id
        self.name = name
        self.kind = kind
        self.isDefault = isDefault
    }

    init?(dictionary d: [String: Any]) {
        guard let id = d["id"] as? Int, let name = d["name"] as? String else { return nil }
        self.init(id: id, name: name, kind: d["kind"] as? String, isDefault: d["default"] as? Bool)
    }
}

/// The last sport and bike chosen on this device, so the pickers start where the user left them.
struct RecordChoices {
    var defaults: UserDefaults = .standard
    private static let sportKey = "record-sport", bikeKey = "record-bike"

    var sport: Sport {
        get { Sport(stored: defaults.string(forKey: Self.sportKey)) }
        nonmutating set { defaults.set(newValue.rawValue, forKey: Self.sportKey) }
    }

    var bikeId: Int? {
        get { defaults.object(forKey: Self.bikeKey) as? Int }
        nonmutating set { defaults.set(newValue, forKey: Self.bikeKey) }
    }
}
