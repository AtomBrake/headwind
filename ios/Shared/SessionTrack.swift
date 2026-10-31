import Foundation

/// One second of a timed session (an indoor ride, a treadmill run, strength) from the phone's Bluetooth sensors: there's no GPS fix to hang
/// the readings on, so they're taken every second instead and journalled, so a crash keeps them. Short keys: there are 3,600 of these an hour.
struct SessionSample: Codable, Equatable, Sendable {
    var time: Date
    var hr: Int?
    var power: Int?
    var cadence: Int?
    /// m/s.
    var speed: Double?
    /// Metres since the start, by sensor (`DistanceFollower`).
    var distance: Double?

    init(time: Date, hr: Int? = nil, power: Int? = nil, cadence: Int? = nil, speed: Double? = nil, distance: Double? = nil) {
        self.time = time
        self.hr = hr
        self.power = power
        self.cadence = cadence
        self.speed = speed
        self.distance = distance
    }

    private enum CodingKeys: String, CodingKey {
        case time = "t", hr, power = "w", cadence = "cad", speed = "v", distance = "d"
    }
}

/// Sums for average heart rate, power and cadence, the same way for GPS points and a timed session's samples.
struct SensorAverages: Equatable, Sendable {
    private var heartRateSum = 0, heartRateCount = 0
    private var powerSum = 0, powerCount = 0
    private var cadenceSum = 0, cadenceCount = 0

    init() {}

    mutating func add(hr: Int?, power: Int?, cadence: Int?) {
        if let hr, hr > 0 {
            heartRateSum += hr
            heartRateCount += 1
        }
        if let power, power >= 0 {
            powerSum += power
            powerCount += 1
        }
        if let cadence, cadence > 0 {
            cadenceSum += cadence
            cadenceCount += 1
        }
    }

    var heartRate: Int? { heartRateCount > 0 ? heartRateSum / heartRateCount : nil }
    /// Over the readings that had one, zeros included (coasting is part of a ride's average power, as on a head unit).
    var power: Int? { powerCount > 0 ? powerSum / powerCount : nil }
    /// Over the readings where the cranks turned: coasting would drag it down, as Garmin leaves it out.
    var cadence: Int? { cadenceCount > 0 ? cadenceSum / cadenceCount : nil }
}

/// A timed session's samples and what they add up to.
struct SessionTrack: Sendable {
    private(set) var samples: [SessionSample] = []
    private var averages = SensorAverages()
    private(set) var maxSpeed = 0.0

    init() {}

    init(samples: [SessionSample]) {
        for s in samples { add(s) }
    }

    /// Returns whether it was kept: one no later than the last is a duplicate.
    @discardableResult
    mutating func add(_ sample: SessionSample) -> Bool {
        if let last = samples.last, sample.time <= last.time { return false }
        samples.append(sample)
        averages.add(hr: sample.hr, power: sample.power, cadence: sample.cadence)
        if let v = sample.speed { maxSpeed = max(maxSpeed, v) }
        return true
    }

    var isEmpty: Bool { samples.isEmpty }
    var latest: SessionSample? { samples.last }
    /// Metres by sensor; 0 with none.
    var distance: Double { samples.last { $0.distance != nil }?.distance ?? 0 }
    var averageHeartRate: Int? { averages.heartRate }
    var averagePower: Int? { averages.power }
    var averageCadence: Int? { averages.cadence }
}
