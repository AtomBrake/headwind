import Foundation

/// Accumulates fixes into track segments and running totals while a ride records. Pure value type, so the
/// iPhone and Watch recorders share it and the arithmetic is unit-tested without a GPS.
///
/// The thresholds mirror what the server does when it re-parses the GPX (services/parser.py), so the numbers
/// on screen during the ride match what Headwind shows afterwards as closely as possible.
struct RideTracker: Sendable {
    /// Fixes less accurate than this are dropped (a phone in a pocket under trees can report ±100 m).
    static let maxAccuracy = 50.0
    /// At or above this speed counts as moving — gpxpy's default stopped-speed threshold, which the server uses for rides.
    static let movingSpeed = 1.0
    /// Faster than this between two fixes is a GPS jump, not riding (the server's own plausibility cap).
    static let maxPlausibleSpeed = 30.0
    /// Climbing is counted once altitude has risen this far from the last low point, to ignore GPS altitude jitter.
    static let climbHysteresis = 3.0

    /// One array per stretch between pauses; each becomes a <trkseg> so paused time isn't drawn as a straight line.
    private(set) var segments: [[RidePoint]] = [[]]
    private(set) var isPaused = false
    private(set) var distance = 0.0
    private(set) var movingTime: TimeInterval = 0
    private(set) var elevationGain = 0.0
    private(set) var maxSpeed = 0.0
    private(set) var currentSpeed = 0.0
    private var elevationRef: Double?
    private var heartRateSum = 0
    private var heartRateCount = 0
    private var powerSum = 0
    private var powerCount = 0
    private var cadenceSum = 0
    private var cadenceCount = 0

    var points: [RidePoint] { segments.flatMap { $0 } }
    var pointCount: Int { segments.reduce(0) { $0 + $1.count } }
    var lastPoint: RidePoint? { segments.last(where: { !$0.isEmpty })?.last }
    var averageSpeed: Double { movingTime > 0 ? distance / movingTime : 0 }
    var averageHeartRate: Int? { heartRateCount > 0 ? heartRateSum / heartRateCount : nil }
    /// Over the fixes that had a reading, zeros included (coasting is part of a ride's average power, as on a head unit).
    var averagePower: Int? { powerCount > 0 ? powerSum / powerCount : nil }
    /// Over the fixes where the cranks turned: coasting would drag it down, as Garmin leaves it out.
    var averageCadence: Int? { cadenceCount > 0 ? cadenceSum / cadenceCount : nil }

    init() {}

    /// Rebuild from a recovered journal.
    init(segments: [[RidePoint]]) {
        for (i, segment) in segments.enumerated() {
            if i > 0 { resume() }
            for point in segment { add(point) }
        }
    }

    mutating func pause() {
        isPaused = true
        currentSpeed = 0
    }

    /// Fixes after this go in a new segment (unless nothing was recorded since the last one began).
    mutating func resume() {
        isPaused = false
        if !(segments.last?.isEmpty ?? true) { segments.append([]) }
    }

    /// Returns whether the fix was kept.
    @discardableResult
    mutating func add(_ point: RidePoint) -> Bool {
        guard !isPaused else { return false }
        if let accuracy = point.accuracy, accuracy < 0 || accuracy > Self.maxAccuracy { return false }

        // Distance and speed only within a segment: the gap across a pause isn't ridden distance.
        if let previous = segments[segments.count - 1].last {
            let dt = point.time.timeIntervalSince(previous.time)
            guard dt > 0 else { return false }
            let d = previous.distance(to: point)
            guard d / dt <= Self.maxPlausibleSpeed else { return false }
            distance += d
            let speed = point.speed ?? d / dt
            currentSpeed = speed
            maxSpeed = max(maxSpeed, speed)
            if speed >= Self.movingSpeed { movingTime += min(dt, 30) }
        } else if let previous = lastPoint, point.time <= previous.time {
            return false
        }

        if let ele = point.ele {
            if let ref = elevationRef {
                if ele - ref >= Self.climbHysteresis {
                    elevationGain += ele - ref
                    elevationRef = ele
                } else if ref - ele >= Self.climbHysteresis {
                    elevationRef = ele
                }
            } else {
                elevationRef = ele
            }
        }
        if let hr = point.hr, hr > 0 {
            heartRateSum += hr
            heartRateCount += 1
        }
        if let power = point.power, power >= 0 {
            powerSum += power
            powerCount += 1
        }
        if let cadence = point.cadence, cadence > 0 {
            cadenceSum += cadence
            cadenceCount += 1
        }
        segments[segments.count - 1].append(point)
        return true
    }
}

/// Wall-clock time spent recording, excluding pauses.
struct ActiveClock: Codable, Sendable {
    private(set) var startedAt: Date?
    private var accumulated: TimeInterval = 0
    private var runningSince: Date?

    var isRunning: Bool { runningSince != nil }

    mutating func start(at date: Date = .now) {
        startedAt = date
        accumulated = 0
        runningSince = date
    }

    mutating func pause(at date: Date = .now) {
        guard let since = runningSince else { return }
        accumulated += date.timeIntervalSince(since)
        runningSince = nil
    }

    mutating func resume(at date: Date = .now) {
        guard runningSince == nil, startedAt != nil else { return }
        runningSince = date
    }

    func elapsed(at date: Date = .now) -> TimeInterval {
        accumulated + (runningSince.map { date.timeIntervalSince($0) } ?? 0)
    }
}
