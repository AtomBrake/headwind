import Foundation

// Shapes of the routes/api_v1.py responses. Nearly everything is optional: the server omits or nulls fields when the
// rider hasn't set a goal, synced Garmin, logged weight etc., and the app should show a dash rather than fail.

/// GET /api/v1/ping
struct PingInfo: Codable, Equatable {
    var ok: Bool?
    var api: Int?
    var rider: String?
    var units: String?
    var calorieAdjustPct: Double?
    var serverTime: String?
    /// The rider's bikes that aren't archived, for the bike picker (older servers don't send them).
    var bikes: [Bike]?
}

/// GET /api/v1/today: the home screen in one request.
struct Today: Decodable {
    var date: String
    var rider: String?
    var goals: Goals?
    var eaten: Macros?
    var remaining: Remaining?
    var waterMl: Double?
    var waterGoalMl: Double?
    var burned: Double?
    var burnSource: String?
    var steps: Steps?
    var weight: WeightSnapshot?
    var entries: [FoodEntry]?
    var workouts: [Workout]?

    struct Goals: Decodable {
        var cal: Double?
        var protein: Double?
        var carbs: Double?
        var fat: Double?
        var fibre: Double?
        var water: Double?
    }

    struct Macros: Decodable {
        var calories: Double?
        var protein: Double?
        var carbs: Double?
        var fat: Double?
        var fibre: Double?
    }

    struct Remaining: Decodable {
        var calories: Double?
        var protein: Double?
    }

    struct Steps: Decodable {
        var today: Double?
        var goal: Double?
    }

    /// raw/trend are always kilograms; `unit` is the rider's display preference (stlb, kg or lb).
    struct WeightSnapshot: Decodable {
        var raw: Double?
        var trend: Double?
        var unit: String?
        var bodyFat: Double?
    }
}

struct FoodEntry: Decodable, Identifiable {
    var id: Int
    var foodName: String
    var brand: String?
    var calories: Double?
    var protein: Double?
    var carbs: Double?
    var fat: Double?
    var servingG: Double?
    var quantity: Double?
    var mealType: String?
}

struct Workout: Decodable, Identifiable {
    var id: String
    var sport: String?
    var name: String?
    var startDateLocal: String?
    var distance: Double?
    var movingTime: Double?
    var calories: Double?
    var steps: Double?
    /// What a person reads for the sport ("Indoor run") and its stat group (ride, foot, swim, or the sport); older servers send neither.
    var label: String?
    var group: String?
}

/// GET /api/v1/overview: the web dashboard's numbers.
struct Overview: Decodable {
    var rider: String?
    var all: RideTotals
    var week: RideTotals
    var month: RideTotals
    var year: RideTotals
    var workouts: [String: WorkoutTotals]?
    var weekly: [WeekBar]
    var recovery: Recovery?
    /// Every sport group the rider has, with its own totals (newer servers; older ones send only the ride totals above).
    var groups: [SportGroup]?
    /// The last 12 weeks with each group's figures.
    var weeklyAll: [WeekAll]?

    func totals(for period: Period) -> RideTotals {
        switch period {
        case .week: week
        case .month: month
        case .year: year
        case .all: all
        }
    }

    enum Period: String, CaseIterable, Identifiable {
        case week, month, year, all
        var id: Self { self }
        var title: String {
            switch self {
            case .week: "Week"
            case .month: "Month"
            case .year: "Year"
            case .all: "All time"
            }
        }
    }

    struct RideTotals: Decodable {
        var rides: Int
        var distanceM: Double
        var elevM: Double
        var movingS: Double
        var calories: Double
    }

    struct WorkoutTotals: Decodable {
        var count: Int
        var distanceM: Double
        var calories: Double
    }

    struct WeekBar: Decodable, Identifiable {
        var label: String
        var distanceM: Double
        var elevM: Double
        var calories: Double
        var current: Bool
        var id: String { label }
    }

    struct Recovery: Decodable {
        var date: String?
        var restingHR: Double?
        var hrv: Double?
        var sleepHours: Double?
        var sleepScore: Double?
        var bodyBattery: Double?
        var steps: Double?
        /// "rmssd" (Garmin, overnight) or "sdnn" (Apple Watch, through the day): not comparable, so the card says which.
        var hrvKind: String?
        /// "garmin", "apple_health", or both joined by "+".
        var source: String?
    }

    /// One stat group's totals (routes/api_v1.py _group_totals).
    struct SportGroup: Decodable, Identifiable {
        var key: String
        var label: String
        var style: String?
        var hasDistance: Bool?
        var totals: [String: GroupTotals]
        var id: String { key }
    }

    struct GroupTotals: Decodable {
        var count: Int
        var distanceM: Double
        var movingS: Double
        var elevM: Double
        var calories: Double
    }

    struct WeekAll: Decodable, Identifiable {
        var label: String
        var current: Bool
        var by: [String: GroupWeek]
        var id: String { label }
    }

    struct GroupWeek: Decodable {
        var distanceM: Double
        var movingS: Double
        var elevM: Double
        var calories: Double
    }
}

/// GET /api/v1/rides: one page of every activity, newest first.
struct ActivityPage: Decodable {
    var total: Int
    var offset: Int
    var items: [ActivityItem]
}

struct ActivityItem: Decodable, Identifiable, Hashable {
    var kind: String
    var id: String
    var name: String?
    var sport: String?
    var label: String?
    var group: String?
    var date: String
    var distanceM: Double?
    var movingS: Double?
    var elevM: Double?
    var avgSpeedMps: Double?
    var avgHr: Double?
    var calories: Double?
    var city: String?

    var title: String { (name?.isEmpty == false ? name : nil) ?? label ?? sport ?? "Activity" }
}

/// GET /api/v1/rides/<kind>/<id>: one activity with its track, series and photos.
struct ActivityDetail: Decodable {
    var kind: String
    var id: String
    var name: String?
    var sport: String?
    var label: String?
    var date: String?
    var city: String?
    var source: String?
    var distanceM: Double?
    var movingS: Double?
    var elapsedS: Double?
    var elevM: Double?
    var avgSpeedMps: Double?
    var maxSpeedMps: Double?
    var avgHr: Double?
    var maxHr: Double?
    var avgWatts: Double?
    var maxWatts: Double?
    var cadence: Double?
    var calories: Double?
    var steps: Double?
    var weather: Weather?
    var description: String?
    var notes: String?
    var track: [[Double]]?
    var series: Series?
    var photos: [Photo]?

    struct Weather: Decodable {
        var summary: String?
        var tempC: Double?
        var windKph: Double?
        var rainMm: Double?
    }

    struct Series: Decodable {
        var elevation: [Point]?
        var speed: [Point]?
        var heartrate: [Point]?
        var watts: [Point]?
    }

    struct Point: Decodable, Identifiable {
        var d: Double
        var v: Double
        var id: Double { d }
    }

    struct Photo: Decodable, Identifiable, Hashable {
        var id: Int
        var caption: String?
        var url: String
        var thumbUrl: String
    }
}

/// GET /api/v1/health: what Apple Health has sent, per metric.
struct HealthSummary: Decodable {
    var metrics: [String: Metric?]

    struct Metric: Decodable {
        var last: String?
        var days: Int
    }
}
