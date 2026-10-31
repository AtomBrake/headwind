import Foundation

/// Display formatting that follows the server's Settings: `units` from /ping for distance and climbing,
/// and the nutrition weight unit (stlb / kg / lb) that comes with each weight snapshot.
struct Units {
    var metric: Bool

    init(system: String?) {
        metric = (system ?? "metric") == "metric"
    }

    func distance(metres m: Double) -> String {
        let value = metric ? m / 1000 : m / 1609.344
        let digits = value >= 100 ? 0 : 1
        return value.formatted(.number.precision(.fractionLength(digits))) + (metric ? " km" : " mi")
    }

    /// A swim's distance reads in metres or yards ("1,500 m"), everything else in km or miles.
    func distance(metres m: Double, sport: Sport) -> String {
        guard sport.isSwim else { return distance(metres: m) }
        let value = metric ? m : m / 0.9144
        return value.formatted(.number.precision(.fractionLength(0))) + (metric ? " m" : " yd")
    }

    func elevation(metres m: Double) -> String {
        let value = metric ? m : m * 3.28084
        return value.formatted(.number.precision(.fractionLength(0))) + (metric ? " m" : " ft")
    }

    func speed(metresPerSecond v: Double) -> String {
        let value = metric ? v * 3.6 : v * 2.236936
        return value.formatted(.number.precision(.fractionLength(1))) + (metric ? " km/h" : " mph")
    }

    /// Minutes per kilometre or mile on foot: "5:32 /km". A dash when standing still, rather than hours per kilometre.
    func pace(metresPerSecond v: Double) -> String {
        guard v >= 0.3 else { return "–" + (metric ? " /km" : " /mi") }
        let total = Int(((metric ? 1000 : 1609.344) / v).rounded())
        return String(format: "%d:%02d", total / 60, total % 60) + (metric ? " /km" : " /mi")
    }

    /// Minutes per 100 m (or 100 yd) in the water: "1:52 /100m".
    func swimPace(metresPerSecond v: Double) -> String {
        let unit = metric ? " /100m" : " /100yd"
        guard v >= 0.05 else { return "–" + unit }
        let total = Int(((metric ? 100 : 91.44) / v).rounded())
        return String(format: "%d:%02d", total / 60, total % 60) + unit
    }

    /// Speed for rides, pace on foot, per 100 m for swims, as the server's dashboard shows them (services/sports.rate_style).
    func rate(metresPerSecond v: Double, sport: Sport) -> String {
        if sport.isSwim { return swimPace(metresPerSecond: v) }
        return sport.isOnFoot ? pace(metresPerSecond: v) : speed(metresPerSecond: v)
    }

    /// The same for a stat group the server sends ('speed', 'pace', 'swim'; 'time' has none).
    func rate(metresPerSecond v: Double, style: String?) -> String? {
        switch style {
        case "pace": pace(metresPerSecond: v)
        case "swim": swimPace(metresPerSecond: v)
        case "time": nil
        default: speed(metresPerSecond: v)
        }
    }

    static func rateCaption(_ sport: Sport, average: Bool = false) -> String {
        let pace = sport.isOnFoot || sport.isSwim
        switch (pace, average) {
        case (false, false): return "Speed"
        case (false, true): return "Avg speed"
        case (true, false): return "Pace"
        case (true, true): return "Avg pace"
        }
    }

    /// Stopwatch style for a ride in progress: 0:42, 12:05, 1:03:27.
    static func clock(seconds s: Double) -> String {
        let total = max(0, Int(s))
        let h = total / 3600, m = (total % 3600) / 60, sec = total % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, sec) : String(format: "%d:%02d", m, sec)
    }

    static func duration(seconds s: Double) -> String {
        let total = Int(s.rounded())
        let h = total / 3600, m = (total % 3600) / 60
        if h > 0 { return "\(h)h \(String(format: "%02d", m))m" }
        return m > 0 ? "\(m)m" : "\(total)s"
    }

    static func weight(kg: Double, unit: String?) -> String {
        switch unit {
        case "kg":
            return kg.formatted(.number.precision(.fractionLength(1))) + " kg"
        case "lb":
            return (kg * 2.20462).formatted(.number.precision(.fractionLength(1))) + " lb"
        default:   // stlb, the server's default
            let pounds = kg * 2.20462
            var stone = Int(pounds / 14)
            var rest = ((pounds - Double(stone) * 14) * 10).rounded() / 10
            if rest >= 14 { stone += 1; rest -= 14 }
            return "\(stone) st " + rest.formatted(.number.precision(.fractionLength(1))) + " lb"
        }
    }

    static func whole(_ value: Double?) -> String {
        guard let value else { return "–" }
        return value.formatted(.number.precision(.fractionLength(0)))
    }
}
