import Foundation

/// What a recording is, chosen before Start and locked once recording. The raw value is what's stored on the device (journal, recordings, Watch
/// metadata); `serverSport` is the server's name for it (services/sports.py: RIDES, ON_FOOT, VirtualRun, Swim, Strength, HIIT, Yoga).
///
/// Most sports record a GPS track and go up as GPX. The rest (an indoor ride, a treadmill, a pool swim, strength, HIIT, yoga) are timed only: they go
/// to POST /api/v1/activities with their time, distance (where the Watch measures one) and calories.
enum Sport: String, Codable, CaseIterable, Identifiable, Sendable {
    case ride = "Ride"
    case ebike = "EBikeRide"
    case run = "Run"
    case walk = "Walk"
    case hike = "Hike"
    case indoorRide = "VirtualRide"
    case treadmill = "VirtualRun"
    case poolSwim = "Swim"
    case openWaterSwim = "OpenWaterSwim"
    case strength = "Strength"
    case hiit = "HIIT"
    case yoga = "Yoga"

    var id: Self { self }

    var title: String {
        switch self {
        case .ride: "Ride"
        case .ebike: "E-bike ride"
        case .run: "Run"
        case .walk: "Walk"
        case .hike: "Hike"
        case .indoorRide: "Indoor ride"
        case .treadmill: "Treadmill run"
        case .poolSwim: "Pool swim"
        case .openWaterSwim: "Open water swim"
        case .strength: "Strength"
        case .hiit: "HIIT"
        case .yoga: "Yoga"
        }
    }

    /// The end of the activity's name: "Morning Ride", "Evening E-bike Ride", "Night Run", "Morning Swim".
    var nameWord: String {
        switch self {
        case .ride: "Ride"
        case .ebike: "E-bike Ride"
        case .run: "Run"
        case .walk: "Walk"
        case .hike: "Hike"
        case .indoorRide: "Indoor Ride"
        case .treadmill: "Treadmill Run"
        case .poolSwim, .openWaterSwim: "Swim"
        case .strength: "Strength Session"
        case .hiit: "HIIT"
        case .yoga: "Yoga"
        }
    }

    var systemImage: String {
        switch self {
        case .ride: "bicycle"
        case .ebike: "bolt.fill"
        case .run: "figure.run"
        case .walk: "figure.walk"
        case .hike: "figure.hiking"
        case .indoorRide: "figure.indoor.cycle"
        case .treadmill: "figure.run.circle"
        case .poolSwim: "figure.pool.swim"
        case .openWaterSwim: "figure.open.water.swim"
        case .strength: "figure.strengthtraining.traditional"
        case .hiit: "figure.highintensity.intervaltraining"
        case .yoga: "figure.yoga"
        }
    }

    /// The server's sport name (services/sports.py). Both swims are a Swim there.
    var serverSport: String {
        switch self {
        case .openWaterSwim: "Swim"
        default: rawValue
        }
    }

    /// Rides have a bike, and a GPS ride goes to POST /api/v1/rides.
    var isRide: Bool { self == .ride || self == .ebike || self == .indoorRide }

    /// Records a GPS track, written as GPX. The others are timed only.
    var usesGPS: Bool {
        switch self {
        case .ride, .ebike, .run, .walk, .hike, .openWaterSwim: true
        case .indoorRide, .treadmill, .poolSwim, .strength, .hiit, .yoga: false
        }
    }

    /// Has a distance at all. Strength, HIIT and yoga don't; an indoor ride has one only from a sensor, a treadmill and a pool swim from the Watch.
    var hasDistance: Bool { ![.strength, .hiit, .yoga].contains(self) }

    var isSwim: Bool { self == .poolSwim || self == .openWaterSwim }

    /// On foot: pace per km or mile.
    var isOnFoot: Bool { [.run, .walk, .hike, .treadmill].contains(self) }

    /// What the iPhone can record: everything but swims (it stays on the side of the pool). A treadmill or indoor ride is a timer there.
    var phoneCanRecord: Bool { !isSwim }

    static var phoneSports: [Sport] { allCases.filter(\.phoneCanRecord) }

    /// The GPX <type>, which services/parser.py _SPORT_MAP turns back into this sport. Only GPS sports are written as GPX.
    var gpxType: String {
        switch self {
        case .ride: "cycling"
        case .ebike: "ebike"
        case .run: "running"
        case .walk: "walking"
        case .hike: "hiking"
        case .indoorRide: "vride"
        case .treadmill: "virtualrun"
        case .poolSwim, .openWaterSwim: "swimming"
        case .strength: "strength_training"
        case .hiit: "hiit"
        case .yoga: "yoga"
        }
    }

    /// Unknown or missing values (an older app's recording, a sport this build doesn't know) are rides, as every recording used to be.
    init(stored raw: String?) {
        self = raw.flatMap(Sport.init(rawValue:)) ?? .ride
    }
}

/// Icons and groups for any sport the server sends (an activity from Garmin, Strava or Apple Health: a paddle, a ski day), the way
/// services/sports.py icon() and stat_group() read them. The app records only `Sport`, but shows everything.
enum ActivitySport {
    static func systemImage(_ sport: String?) -> String {
        if let known = sport.flatMap(Sport.init(rawValue:)) { return known.systemImage }
        let s = (sport ?? "").lowercased()
        if s.isEmpty || s.contains("ride") || s.contains("cycl") { return s.contains("virtual") || s.contains("indoor") ? "figure.indoor.cycle" : "bicycle" }
        if s.contains("run") { return "figure.run" }
        if s.contains("swim") { return "figure.pool.swim" }
        if s.contains("surf") { return "figure.surfing" }
        if s.contains("paddl") || s.contains("kayak") || s.contains("canoe") || s.contains("row") || s.contains("water") { return "figure.rower" }
        if s.contains("ski") { return "figure.skiing.downhill" }
        if s.contains("skat") { return "figure.skating" }
        if s.contains("golf") { return "figure.golf" }
        if s.contains("climb") { return "figure.climbing" }
        if s.contains("walk") || s.contains("hike") || s.contains("snowshoe") { return "figure.walk" }
        if s.contains("yoga") { return "figure.yoga" }
        if s.contains("strength") || s.contains("weight") { return "figure.strengthtraining.traditional" }
        if s.contains("hiit") { return "figure.highintensity.intervaltraining" }
        return "figure.mixed.cardio"
    }

    /// services/sports.stat_group: 'ride', 'foot', 'swim', or the sport itself.
    static func group(_ sport: String?) -> String {
        let s = (sport ?? "").lowercased()
        if s.isEmpty || s.contains("ride") || s.contains("cycl") { return "ride" }
        let squashed = s.filter(\.isLetter)
        if ["walk", "run", "hike", "trailrun", "virtualrun"].contains(squashed) { return "foot" }
        if squashed.contains("swim") { return "swim" }
        return sport ?? ""
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
    private static let sportKey = "record-sport", bikeKey = "record-bike", lapKey = "record-pool-length"

    var sport: Sport {
        get { Sport(stored: defaults.string(forKey: Self.sportKey)) }
        nonmutating set { defaults.set(newValue.rawValue, forKey: Self.sportKey) }
    }

    var bikeId: Int? {
        get { defaults.object(forKey: Self.bikeKey) as? Int }
        nonmutating set { defaults.set(newValue, forKey: Self.bikeKey) }
    }

    /// The pool's length in metres for a pool swim (the Watch counts lengths), 25 unless chosen.
    var poolLength: Double {
        get { (defaults.object(forKey: Self.lapKey) as? Double) ?? 25 }
        nonmutating set { defaults.set(newValue, forKey: Self.lapKey) }
    }
}
