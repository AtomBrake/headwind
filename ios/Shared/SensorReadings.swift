import Foundation

/// What the paired sensors say now, as plain values: what `PhoneRideRecorder` puts on each point. Nil is "no sensor sends it", or one that
/// has gone quiet (out of range, asleep); 0 is a real reading (coasting, stopped).
struct SensorReadings: Equatable, Sendable {
    var heartRate: Int?
    /// Watts, averaged over the last 3 s as head units show it: a single reading jumps about with every pedal stroke.
    var power: Int?
    /// rpm.
    var cadence: Int?
    /// m/s.
    var speed: Double?
    /// Metres since the sensor began counting: only the difference between two readings means anything (see `DistanceFollower`).
    var distance: Double?
    /// The sensor `distance` comes from, so a switch to another sensor's count isn't taken for distance ridden.
    var distanceSource: UUID?

    init(heartRate: Int? = nil, power: Int? = nil, cadence: Int? = nil, speed: Double? = nil, distance: Double? = nil,
         distanceSource: UUID? = nil) {
        self.heartRate = heartRate
        self.power = power
        self.cadence = cadence
        self.speed = speed
        self.distance = distance
        self.distanceSource = distanceSource
    }

    var isEmpty: Bool { heartRate == nil && power == nil && cadence == nil && speed == nil && distance == nil }

    /// For a sport that isn't a ride: a heart rate strap is worth recording on a run, a trainer left on is not.
    var heartRateOnly: SensorReadings { SensorReadings(heartRate: heartRate) }

    /// One sensor's readings, with what it is.
    struct Part: Sendable {
        var kind: SensorKind
        var id: UUID
        var readings: SensorReadings
    }

    /// Several sensors' readings as one, each value from the sensor best placed to give it: heart rate from a strap before a trainer's relayed
    /// one, power from a power meter before a trainer's, cadence and speed from a speed and cadence sensor first, distance from a trainer (it
    /// counts it itself) before a wheel sensor.
    static func combine(_ parts: [Part]) -> SensorReadings {
        func pick<T>(_ order: [SensorKind], _ value: KeyPath<SensorReadings, T?>) -> (T, UUID)? {
            let ranked = parts.sorted { rank($0.kind, in: order) < rank($1.kind, in: order) }
            return ranked.lazy.compactMap { part in part.readings[keyPath: value].map { ($0, part.id) } }.first
        }
        let distance = pick([.trainer, .speedCadence, .power], \.distance)
        return SensorReadings(heartRate: pick([.heartRate, .trainer], \.heartRate)?.0,
                              power: pick([.power, .trainer], \.power)?.0,
                              cadence: pick([.speedCadence, .power, .trainer], \.cadence)?.0,
                              speed: pick([.speedCadence, .trainer, .power], \.speed)?.0,
                              distance: distance?.0, distanceSource: distance?.1)
    }

    private static func rank(_ kind: SensorKind, in order: [SensorKind]) -> Int { order.firstIndex(of: kind) ?? order.count }
}

/// The wheel's circumference, which turns a wheel sensor's revolutions into speed and distance. 2105 mm (a 700×25c tyre) unless chosen.
struct WheelSize {
    static let defaultMillimetres = 2105
    static let range = 1000...3000
    /// Common sizes, for the picker (the figures printed on most tyre makers' charts).
    static let common: [(name: String, mm: Int)] = [
        ("700×23c", 2096), ("700×25c", 2105), ("700×28c", 2136), ("700×32c", 2155), ("700×38c", 2180), ("700×45c", 2242),
        ("650b×47", 2079), ("26×2.1", 2068), ("27.5×2.25", 2177), ("29×2.25", 2288), ("29×2.4", 2326),
    ]

    var defaults: UserDefaults = .standard
    private static let key = "sensor-wheel-mm"

    var millimetres: Int {
        get {
            let stored = defaults.integer(forKey: Self.key)
            return Self.range.contains(stored) ? stored : Self.defaultMillimetres
        }
        nonmutating set { defaults.set(min(max(newValue, Self.range.lowerBound), Self.range.upperBound), forKey: Self.key) }
    }

    var metres: Double { Double(millimetres) / 1000 }
}

/// Revolutions per second from a cumulative count and event time, which is how wheel and crank sensors report: the rate is the
/// revolutions between two readings over the time between their last events. Both counters wrap (the time every 64 s, a crank's count at
/// 65536), and are read modulo their size. No new revolution for `stoppedAfter` is stopped; no packet at all for `goneAfter` is no reading.
struct RevolutionRate: Sendable {
    static let stoppedAfter: TimeInterval = 3
    static let goneAfter: TimeInterval = 5

    /// The count's modulus: 2³² for a wheel, 2¹⁶ for a crank.
    let modulus: UInt64
    let ticksPerSecond: Double
    /// Faster than this is a glitch, not riding.
    let maxPerSecond: Double

    private var lastCount: UInt32?
    private var lastTime: UInt16 = 0
    private var lastPacket: Date?
    private var lastChange: Date?
    private var rate = 0.0
    /// Revolutions counted since this began (for distance), leaving out jumps no rider could make.
    private(set) var revolutions: UInt64 = 0

    init(modulus: UInt64, ticksPerSecond: Double, maxPerSecond: Double) {
        self.modulus = modulus
        self.ticksPerSecond = ticksPerSecond
        self.maxPerSecond = maxPerSecond
    }

    /// 100 km/h on a 2.1 m wheel is 13 revolutions a second.
    static func wheel(ticksPerSecond: Double = 1024) -> RevolutionRate {
        RevolutionRate(modulus: 1 << 32, ticksPerSecond: ticksPerSecond, maxPerSecond: 20)
    }

    /// 250 rpm.
    static var crank: RevolutionRate { RevolutionRate(modulus: 1 << 16, ticksPerSecond: 1024, maxPerSecond: 250.0 / 60) }

    mutating func update(_ r: Revolutions, at now: Date) {
        defer {
            lastCount = r.count
            lastTime = r.eventTime
            lastPacket = now
        }
        guard let previousCount = lastCount, let previousPacket = lastPacket else {
            lastChange = now
            return
        }
        let counted = (UInt64(r.count) + modulus - UInt64(previousCount)) % modulus
        guard counted > 0 else { return }
        // More revolutions than could have happened since the last packet: the sensor restarted, or its count jumped.
        let wall = max(now.timeIntervalSince(previousPacket), 1)
        guard Double(counted) <= maxPerSecond * wall * 1.5 + 2 else {
            rate = 0
            lastChange = now
            return
        }
        revolutions += counted
        // After a long stop the event time has wrapped (every 64 s) and the gap can't be told: wait for the next revolution.
        let sinceChange = lastChange.map { now.timeIntervalSince($0) } ?? 0
        lastChange = now
        let ticks = Double((Int(r.eventTime) - Int(lastTime) + 65536) % 65536)
        guard ticks > 0, sinceChange < 60 else { return }
        let perSecond = Double(counted) * ticksPerSecond / ticks
        if perSecond <= maxPerSecond { rate = perSecond }
    }

    func perSecond(at now: Date) -> Double? {
        guard let lastPacket, now.timeIntervalSince(lastPacket) < Self.goneAfter else { return nil }
        guard let lastChange, now.timeIntervalSince(lastChange) < Self.stoppedAfter else { return 0 }
        return rate
    }
}

/// The mean of the readings in the last few seconds (power's 3 s average).
struct RollingAverage: Sendable {
    var window: TimeInterval = 3
    private var samples: [(at: Date, value: Int)] = []

    init(window: TimeInterval = 3) { self.window = window }

    mutating func add(_ value: Int, at now: Date) {
        samples.append((now, value))
        samples.removeAll { now.timeIntervalSince($0.at) > window }
    }

    func average(at now: Date) -> Int? {
        let recent = samples.filter { now.timeIntervalSince($0.at) <= window }
        guard !recent.isEmpty else { return nil }
        return Int((Double(recent.reduce(0) { $0 + $1.value }) / Double(recent.count)).rounded())
    }
}

/// A value and when it came, read back only while it's fresh.
struct Latest<Value: Sendable>: Sendable {
    var value: Value
    var at: Date

    func value(at now: Date, within: TimeInterval = SensorChannel.staleAfter) -> Value? {
        now.timeIntervalSince(at) < within ? value : nil
    }
}

/// One connected sensor: the values it has sent, read back as `SensorReadings`. Kept across a dropped connection, so a wheel sensor's
/// count and a trainer's distance carry on when it comes back.
struct SensorChannel: Sendable {
    /// A reading older than this is no reading: the sensor has gone quiet.
    static let staleAfter: TimeInterval = 5

    private var heartRate: Latest<Int>?
    private var power = RollingAverage()
    private var cscWheel = RevolutionRate.wheel()
    private var cscCrank = RevolutionRate.crank
    private var cpsWheel = RevolutionRate.wheel(ticksPerSecond: 2048)
    private var cpsCrank = RevolutionRate.crank
    private var hasCSCWheel = false
    private var hasCPSWheel = false
    private var trainerPower = RollingAverage()
    private var trainerSpeed: Latest<Double>?
    private var trainerCadence: Latest<Double>?
    private var trainerHeartRate: Latest<Int>?
    private var trainerDistance: Latest<Double>?
    private var trainerDistanceTotal = RunningTotal()

    init() {}

    /// Take one notification. Returns whether it was understood.
    @discardableResult
    mutating func receive(_ characteristic: UInt16, _ data: Data, at now: Date) -> Bool {
        switch characteristic {
        case GATT.heartRateMeasurement:
            guard let m = HeartRateMeasurement(data) else { return false }
            if m.isValid { heartRate = Latest(value: m.bpm, at: now) }
        case GATT.cscMeasurement:
            guard let m = CSCMeasurement(data) else { return false }
            if let wheel = m.wheel { cscWheel.update(wheel, at: now); hasCSCWheel = true }
            if let crank = m.crank { cscCrank.update(crank, at: now) }
        case GATT.cyclingPowerMeasurement:
            guard let m = CyclingPowerMeasurement(data) else { return false }
            power.add(max(0, m.power), at: now)
            if let wheel = m.wheel { cpsWheel.update(wheel, at: now); hasCPSWheel = true }
            if let crank = m.crank { cpsCrank.update(crank, at: now) }
        case GATT.indoorBikeData:
            guard let m = IndoorBikeData(data) else { return false }
            if let v = m.power { trainerPower.add(max(0, v), at: now) }
            if let v = m.speed { trainerSpeed = Latest(value: v, at: now) }
            if let v = m.cadence { trainerCadence = Latest(value: v, at: now) }
            if let v = m.heartRate, v > 0 { trainerHeartRate = Latest(value: v, at: now) }
            if let v = m.distance {
                trainerDistanceTotal.update(v)
                trainerDistance = Latest(value: trainerDistanceTotal.total, at: now)
            }
        default:
            return false
        }
        return true
    }

    func readings(at now: Date, wheelCircumference: Double) -> SensorReadings {
        var r = SensorReadings()
        r.heartRate = heartRate?.value(at: now) ?? trainerHeartRate?.value(at: now)
        r.power = power.average(at: now) ?? trainerPower.average(at: now)
        let rpm = (cscCrank.perSecond(at: now) ?? cpsCrank.perSecond(at: now)).map { $0 * 60 } ?? trainerCadence?.value(at: now)
        r.cadence = rpm.map { Int($0.rounded()) }
        let wheel = hasCSCWheel ? cscWheel : hasCPSWheel ? cpsWheel : nil
        r.speed = wheel?.perSecond(at: now).map { $0 * wheelCircumference } ?? trainerSpeed?.value(at: now)
        if let d = trainerDistance?.value(at: now) {
            r.distance = d
        } else if let wheel, wheel.perSecond(at: now) != nil {
            r.distance = Double(wheel.revolutions) * wheelCircumference
        }
        return r
    }
}

/// A count that only goes up, from a sensor's total that may start again from zero (a trainer switched off and on).
struct RunningTotal: Sendable {
    private var last: Double?
    private(set) var total = 0.0

    mutating func update(_ value: Double) {
        if let last, value >= last { total += value - last }
        last = value
    }
}

/// The distance ridden by sensor during a recording: the sum of the steps between readings of one sensor's count, taken only while recording.
/// A pause, a sensor going quiet or another sensor taking over starts again from its next reading, so none of those count as distance.
struct DistanceFollower: Sendable {
    /// More than this between two readings (a second apart) isn't riding: start again from the new count.
    static let maxStep = 100.0

    /// Nil until a sensor has given a distance.
    private(set) var total: Double?
    private var last: Double?
    private var source: UUID?

    init() {}

    @discardableResult
    mutating func update(_ readings: SensorReadings) -> Double? {
        guard let d = readings.distance else {
            last = nil
            return total
        }
        if let last, readings.distanceSource == source, d >= last, d - last <= Self.maxStep {
            total = (total ?? 0) + d - last
        } else if total == nil {
            total = 0
        }
        last = d
        source = readings.distanceSource
        return total
    }

    /// While paused nothing counts: the first reading after resuming is the new starting point.
    mutating func pause() { last = nil }
}
