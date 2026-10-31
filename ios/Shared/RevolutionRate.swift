import Foundation

/// Turns a sensor's cumulative revolutions and event times into a rate: wheel revolutions into speed and distance,
/// crank revolutions into cadence. Pure value type, fed one `RevolutionData` per notification.
///
/// Sensors notify about once a second whether or not anything turned, and repeat the last event when nothing did,
/// so the rate holds between revolutions and drops to zero once none has come for `stoppedAfter`.
struct RevolutionRate: Sendable {
    /// 16 for crank revolutions, 32 for wheel revolutions.
    let revolutionBits: Int
    /// 1024 for speed and cadence sensors; 2048 for a power meter's wheel data.
    let ticksPerSecond: Double
    /// Faster than this (revolutions per second) isn't riding: a sensor reset or a garbled reading.
    let maxRate: Double
    /// No new revolution for this long means stopped (or coasting, for cadence).
    var stoppedAfter: TimeInterval = 3

    /// Longer than this since the last revolution and the 16-bit event time may have wrapped more than once,
    /// so the time between the two can't be known: start again from the new reading.
    static let maxGap: TimeInterval = 30

    /// For a speed sensor's or a power meter's wheel data. 40 rev/s on a 2.1 m wheel is 300 km/h.
    static func wheel(ticksPerSecond: Double = 1024) -> RevolutionRate {
        RevolutionRate(revolutionBits: 32, ticksPerSecond: ticksPerSecond, maxRate: 40)
    }

    /// For crank revolutions from a cadence sensor or a power meter. 4 rev/s is 240 rpm.
    static func crank() -> RevolutionRate {
        RevolutionRate(revolutionBits: 16, ticksPerSecond: 1024, maxRate: 4)
    }

    private var last: RevolutionData?
    /// When (on the receiver's clock) a reading last brought new revolutions.
    private var lastChangeAt: TimeInterval?
    private var lastRate = 0.0
    /// Every revolution counted since the first reading, for distance. Revolutions across a reset or a long gap aren't counted.
    private(set) var totalRevolutions: UInt64 = 0

    init(revolutionBits: Int, ticksPerSecond: Double, maxRate: Double) {
        self.revolutionBits = revolutionBits
        self.ticksPerSecond = ticksPerSecond
        self.maxRate = maxRate
    }

    /// Takes one notification's data, received at `now` (a monotonic clock in seconds, e.g. the system uptime).
    mutating func add(_ data: RevolutionData, at now: TimeInterval) {
        guard let last, let lastChangeAt else { return baseline(data, at: now) }
        let mask: UInt64 = revolutionBits >= 32 ? 0xFFFF_FFFF : (1 << UInt64(revolutionBits)) - 1
        let revs = (UInt64(data.revolutions) &- UInt64(last.revolutions)) & mask
        guard revs > 0 else { return }                              // a repeat of the last event: nothing turned
        guard now - lastChangeAt <= Self.maxGap else { return baseline(data, at: now) }
        let ticks = data.eventTime &- last.eventTime                // wraps at 65,536 as the sensor's clock does
        guard ticks > 0 else { return }                             // more revolutions at the same instant: garbled
        let rate = Double(revs) / (Double(ticks) / ticksPerSecond)
        guard rate <= maxRate else { return baseline(data, at: now) }  // e.g. the counter went back to 0 after a battery change
        lastRate = rate
        totalRevolutions += revs
        self.last = data
        self.lastChangeAt = now
    }

    /// Revolutions per second at `now`: the last rate, or 0 once nothing has turned for `stoppedAfter`.
    /// nil until two readings have given a rate.
    func rate(at now: TimeInterval) -> Double? {
        guard let lastChangeAt, totalRevolutions > 0 else { return nil }
        return now - lastChangeAt >= stoppedAfter ? 0 : lastRate
    }

    /// rpm, for crank data.
    func rpm(at now: TimeInterval) -> Double? { rate(at: now).map { $0 * 60 } }

    /// m/s and metres, for wheel data, given the wheel's circumference in metres.
    func speed(at now: TimeInterval, circumference: Double) -> Double? { rate(at: now).map { $0 * circumference } }
    func distance(circumference: Double) -> Double { Double(totalRevolutions) * circumference }

    private mutating func baseline(_ data: RevolutionData, at now: TimeInterval) {
        last = data
        lastChangeAt = now
        lastRate = 0
    }
}
