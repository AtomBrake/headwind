import Foundation

// The sensors' readings, combined: pure Swift with no CoreBluetooth, so it's unit-tested without a device.
// SensorManager parses each notification (ios/Shared/SensorParsing.swift) and hands it to a SensorHub;
// PhoneRideRecorder reads the hub's `readings(at:)` at each GPS fix, and every second.

/// What the sensors say right now. Every value is nil when no sensor gives it, or the one that did has gone quiet.
struct SensorReadings: Equatable, Sendable {
    /// Beats per minute.
    var heartRate: Int?
    /// Watts, averaged over the last `SensorHub.powerWindow` (3 s) as head units show it: a single reading jumps about with every pedal stroke.
    var power: Int?
    /// rpm.
    var cadence: Int?
    /// m/s, from a smart trainer or a wheel-speed sensor.
    var speed: Double?
    /// Metres from a trainer or a wheel-speed sensor, counted up since the hub was made. It only grows, so a reader takes the
    /// difference between two readings (as `SensorTally` does). nil until one has reported a distance.
    var distance: Double?

    static let none = SensorReadings()
}

/// What a reading came from. When two sensors give the same thing, the one each quantity prefers is used (see `SensorHub`).
enum ReadingSource: Sendable {
    case heartRateStrap
    /// A speed sensor, a cadence sensor or a combined one (Cycling Speed and Cadence).
    case speedCadenceSensor
    /// A power meter, or a trainer offering only the Cycling Power service.
    case powerMeter
    /// A smart trainer's Indoor Bike Data (Fitness Machine).
    case trainer
}

/// Combines every connected sensor's notifications into one `SensorReadings`.
///
/// Times are a monotonic clock in seconds (the system uptime), as `RevolutionRate` takes them. A sensor that has sent nothing for
/// `staleAfter` gives nothing, so a dropped strap shows no heart rate rather than its last one. When two sensors give the same quantity:
/// - heart rate: a strap, then a trainer passing one on;
/// - power: a power meter, then a trainer (a meter on the bike is what the rider paired it for, and usually the more accurate);
/// - cadence: a cadence sensor, then a power meter, then a trainer;
/// - speed and distance: a trainer (it knows the speed it simulates), then a wheel-speed sensor, then a power meter's wheel data.
struct SensorHub: Sendable {
    static let powerWindow: TimeInterval = 3
    static let staleAfter: TimeInterval = 5
    /// Faster than this between two of a trainer's distance readings isn't riding (108 km/h): its counter was reset or garbled.
    static let maxSpeed: Double = 30
    /// A 700×28c tyre, which most road bikes and smart trainers' virtual wheels are near.
    static let defaultWheelCircumference = 2.105

    static let heartRateOrder: [ReadingSource] = [.heartRateStrap, .trainer]
    static let powerOrder: [ReadingSource] = [.powerMeter, .trainer]
    static let cadenceOrder: [ReadingSource] = [.speedCadenceSensor, .powerMeter, .trainer]
    static let speedOrder: [ReadingSource] = [.trainer, .speedCadenceSensor, .powerMeter]

    /// Metres, for speed and distance from wheel revolutions.
    var wheelCircumference = SensorHub.defaultWheelCircumference

    /// One sensor's readings of one kind: a power meter that is also a cadence sensor is one feed, a trainer's Indoor Bike Data another.
    private struct Feed: Hashable, Sendable {
        var sensor: UUID
        var source: ReadingSource
    }

    private struct Sample: Sendable {
        var value: Double
        var at: TimeInterval
    }

    private struct Revolutions: Sendable {
        var rate: RevolutionRate
        var heard: TimeInterval
    }

    private var feeds: Set<Feed> = []
    private var heartRates: [Feed: Sample] = [:]
    /// The last `powerWindow` of readings, oldest first.
    private var powers: [Feed: [Sample]] = [:]
    private var cranks: [Feed: Revolutions] = [:]
    private var wheels: [Feed: Revolutions] = [:]
    private var trainerCadences: [Feed: Sample] = [:]
    private var trainerSpeeds: [Feed: Sample] = [:]
    /// The trainer's own count of metres, last heard. Kept across a disconnection so the distance ridden meanwhile still counts.
    private var trainerDistances: [Feed: Sample] = [:]
    /// When each feed last gave a distance, to choose the one that counts.
    private var distanceHeard: [Feed: TimeInterval] = [:]
    private var distance: Double?

    // MARK: Notifications in

    mutating func add(_ m: HeartRateMeasurement, from sensor: UUID, at now: TimeInterval) {
        // A strap off the skin sends a meaningless number (often 0, or its last one).
        guard m.skinContact != false, m.bpm > 0 else { return }
        heartRates[feed(sensor, .heartRateStrap)] = Sample(value: Double(m.bpm), at: now)
    }

    mutating func add(_ m: CSCMeasurement, from sensor: UUID, at now: TimeInterval) {
        let f = feed(sensor, .speedCadenceSensor)
        if let wheel = m.wheel { addWheel(wheel, to: f, ticksPerSecond: 1024, at: now) }
        if let crank = m.crank { addCrank(crank, to: f, at: now) }
    }

    mutating func add(_ m: CyclingPowerMeasurement, from sensor: UUID, at now: TimeInterval) {
        let f = feed(sensor, .powerMeter)
        addPower(m.power, to: f, at: now)
        if let wheel = m.wheel { addWheel(wheel, to: f, ticksPerSecond: 2048, at: now) }
        if let crank = m.crank { addCrank(crank, to: f, at: now) }
    }

    /// A trainer may split one reading over several notifications, so each field is kept as it comes.
    mutating func add(_ m: IndoorBikeData, from sensor: UUID, at now: TimeInterval) {
        let f = feed(sensor, .trainer)
        if let power = m.power { addPower(power, to: f, at: now) }
        if let cadence = m.cadence { trainerCadences[f] = Sample(value: cadence, at: now) }
        if let speed = m.speed { trainerSpeeds[f] = Sample(value: speed, at: now) }
        if let hr = m.heartRate, hr > 0 { heartRates[f] = Sample(value: Double(hr), at: now) }
        if let metres = m.totalDistance { addTrainerDistance(Double(metres), to: f, at: now) }
    }

    /// The sensor's connection dropped: forget what it was saying, so a reconnection starts its revolution counts afresh.
    /// Its distance so far stays counted.
    mutating func disconnected(_ sensor: UUID) {
        for f in feeds where f.sensor == sensor {
            heartRates[f] = nil
            powers[f] = nil
            cranks[f] = nil
            wheels[f] = nil
            trainerCadences[f] = nil
            trainerSpeeds[f] = nil
            distanceHeard[f] = nil
        }
        feeds = feeds.filter { $0.sensor != sensor || trainerDistances[$0] != nil }
    }

    // MARK: Readings out

    /// Every sensor's readings combined, or with `sensor`, that one sensor's alone (for the Sensors screen; it has no distance then).
    func readings(at now: TimeInterval, of sensor: UUID? = nil) -> SensorReadings {
        SensorReadings(
            heartRate: best(Self.heartRateOrder, of: sensor) { fresh(heartRates[$0], at: now) }.map { Int($0.rounded()) },
            power: best(Self.powerOrder, of: sensor) { averagePower($0, at: now) }.map { Int($0.rounded()) },
            cadence: best(Self.cadenceOrder, of: sensor) { cadence($0, at: now) }.map { Int($0.rounded()) },
            speed: best(Self.speedOrder, of: sensor) { speed($0, at: now) },
            distance: sensor == nil ? distance : nil
        )
    }

    // MARK: Private

    private mutating func feed(_ sensor: UUID, _ source: ReadingSource) -> Feed {
        let f = Feed(sensor: sensor, source: source)
        feeds.insert(f)
        return f
    }

    private mutating func addPower(_ watts: Int, to f: Feed, at now: TimeInterval) {
        var samples = powers[f] ?? []
        samples.removeAll { now - $0.at >= Self.powerWindow }
        samples.append(Sample(value: Double(max(0, watts)), at: now))     // a little below 0 is back-pedalling
        powers[f] = samples
    }

    private mutating func addCrank(_ data: RevolutionData, to f: Feed, at now: TimeInterval) {
        var crank = cranks[f] ?? Revolutions(rate: .crank(), heard: now)
        crank.rate.add(data, at: now)
        crank.heard = now
        cranks[f] = crank
    }

    private mutating func addWheel(_ data: RevolutionData, to f: Feed, ticksPerSecond: Double, at now: TimeInterval) {
        var wheel = wheels[f] ?? Revolutions(rate: .wheel(ticksPerSecond: ticksPerSecond), heard: now)
        let before = wheel.rate.totalRevolutions
        wheel.rate.add(data, at: now)
        wheel.heard = now
        wheels[f] = wheel
        travelled(Double(wheel.rate.totalRevolutions - before) * wheelCircumference, by: f, at: now)
    }

    private mutating func addTrainerDistance(_ metres: Double, to f: Feed, at now: TimeInterval) {
        let last = trainerDistances[f]
        trainerDistances[f] = Sample(value: metres, at: now)
        guard let last else { return travelled(0, by: f, at: now) }
        let gained = metres - last.value
        // Gone back (the trainer restarted its session) or jumped further than anyone rides: count from the new value.
        let plausible = gained >= 0 && gained <= Self.maxSpeed * (now - last.at) + 10
        travelled(plausible ? gained : 0, by: f, at: now)
    }

    /// Only the preferred feed giving a distance counts, so a trainer and a wheel sensor on the same bike don't add up twice.
    private mutating func travelled(_ metres: Double, by f: Feed, at now: TimeInterval) {
        distanceHeard[f] = now
        let counting = best(Self.speedOrder, of: nil) { g in distanceHeard[g].flatMap { now - $0 <= Self.staleAfter ? g : nil } }
        guard counting == f else { return }
        distance = (distance ?? 0) + metres
    }

    private func fresh(_ sample: Sample?, at now: TimeInterval) -> Double? {
        guard let sample, now - sample.at <= Self.staleAfter else { return nil }
        return sample.value
    }

    private func averagePower(_ f: Feed, at now: TimeInterval) -> Double? {
        guard let samples = powers[f], let latest = samples.last, now - latest.at <= Self.staleAfter else { return nil }
        let recent = samples.filter { now - $0.at < Self.powerWindow }
        guard !recent.isEmpty else { return latest.value }             // a meter that sends less often than every 3 s
        return recent.reduce(0) { $0 + $1.value } / Double(recent.count)
    }

    private func cadence(_ f: Feed, at now: TimeInterval) -> Double? {
        if let crank = cranks[f], now - crank.heard <= Self.staleAfter, let rpm = crank.rate.rpm(at: now) { return rpm }
        return fresh(trainerCadences[f], at: now)
    }

    private func speed(_ f: Feed, at now: TimeInterval) -> Double? {
        if let wheel = wheels[f], now - wheel.heard <= Self.staleAfter,
           let speed = wheel.rate.speed(at: now, circumference: wheelCircumference) { return speed }
        return fresh(trainerSpeeds[f], at: now)
    }

    /// The first value `value` gives, trying the feeds by `order` of their source (several of one source in a fixed order).
    private func best<V>(_ order: [ReadingSource], of sensor: UUID?, _ value: (Feed) -> V?) -> V? {
        for source in order {
            let candidates = feeds
                .filter { $0.source == source && (sensor == nil || $0.sensor == sensor) }
                .sorted { $0.sensor.uuidString < $1.sensor.uuidString }
            for f in candidates {
                if let v = value(f) { return v }
            }
        }
        return nil
    }
}

/// The sensors' side of one recording in `PhoneRideRecorder`: the latest readings, and the distance they gave while recording (not
/// while paused), for an indoor ride's distance.
struct SensorTally: Equatable, Sendable {
    private(set) var latest = SensorReadings.none
    /// Metres.
    private(set) var distance: Double = 0
    private var lastDistance: Double?

    /// Takes the hub's readings. `counting` is false while paused or not recording: the distance moves on without adding up.
    mutating func update(_ readings: SensorReadings, counting: Bool) {
        if let d = readings.distance {
            if counting, let last = lastDistance, d > last { distance += d - last }
            lastDistance = d
        }
        latest = readings
    }
}
