import Foundation

// Decoding what Bluetooth LE fitness sensors send, as pure Swift with no CoreBluetooth, so it's unit-tested
// without a device. The sensor manager (CoreBluetooth, iPhone only) hands each characteristic's `value` here.
// Layouts are the Bluetooth SIG's GATT specifications: every field little-endian, optional fields present by
// their flag bit and in the order the spec lists them.

/// 16-bit Bluetooth SIG assigned numbers for the services and characteristics Headwind reads.
/// CoreBluetooth takes them as `CBUUID(string: GATT.uuidString(...))`.
enum GATT {
    static let heartRateService: UInt16 = 0x180D
    static let cyclingSpeedAndCadenceService: UInt16 = 0x1816
    static let cyclingPowerService: UInt16 = 0x1818
    static let fitnessMachineService: UInt16 = 0x1826
    static let batteryService: UInt16 = 0x180F

    static let heartRateMeasurement: UInt16 = 0x2A37
    static let cscMeasurement: UInt16 = 0x2A5B
    static let cyclingPowerMeasurement: UInt16 = 0x2A63
    static let indoorBikeData: UInt16 = 0x2AD2
    static let batteryLevel: UInt16 = 0x2A19

    /// The four services a sensor is scanned for (battery is read from a sensor once connected, not scanned for).
    static let sensorServices: [UInt16] = [heartRateService, cyclingSpeedAndCadenceService, cyclingPowerService, fitnessMachineService]

    static func uuidString(_ number: UInt16) -> String {
        let hex = String(number, radix: 16, uppercase: true)
        return String(repeating: "0", count: 4 - hex.count) + hex
    }
}

/// Reads little-endian fields off the front of a characteristic value. Every read returns nil once the bytes run
/// out, so a short or garbled notification fails to parse instead of trapping.
struct ByteReader {
    private let bytes: [UInt8]
    private(set) var offset = 0

    init(_ data: Data) { bytes = [UInt8](data) }
    init(_ bytes: [UInt8]) { self.bytes = bytes }

    var remaining: Int { bytes.count - offset }

    mutating func uint8() -> UInt8? {
        guard remaining >= 1 else { return nil }
        defer { offset += 1 }
        return bytes[offset]
    }

    mutating func uint16() -> UInt16? { unsigned(2).map { UInt16($0) } }
    mutating func int16() -> Int16? { uint16().map { Int16(bitPattern: $0) } }
    mutating func uint24() -> UInt32? { unsigned(3).map { UInt32($0) } }
    mutating func uint32() -> UInt32? { unsigned(4).map { UInt32($0) } }

    /// Moves past a field Headwind doesn't use; false when it isn't all there.
    mutating func skip(_ count: Int) -> Bool {
        guard remaining >= count else { return false }
        offset += count
        return true
    }

    private mutating func unsigned(_ count: Int) -> UInt64? {
        guard remaining >= count else { return nil }
        var value: UInt64 = 0
        for i in 0..<count { value |= UInt64(bytes[offset + i]) << (8 * i) }
        offset += count
        return value
    }
}

/// A cumulative revolution count and the time of the last revolution, as speed, cadence and power sensors send
/// them. Speed and cadence come from the difference between two of these (`RevolutionRate`).
struct RevolutionData: Equatable, Sendable {
    var revolutions: UInt32
    /// The sensor's own clock, in ticks of 1/1024 s (1/2048 s for a power meter's wheel data); wraps every 64 s (32 s).
    var eventTime: UInt16
}

/// Heart Rate Measurement (0x2A37).
struct HeartRateMeasurement: Equatable, Sendable {
    var bpm: Int
    /// nil when the strap doesn't say; false when it's not touching skin (its reading is then meaningless).
    var skinContact: Bool?
    /// Kilojoules since the strap was reset, when it counts them.
    var energyExpended: Int?
    /// Beat-to-beat intervals in seconds, oldest first (sent in 1/1024 s).
    var rrIntervals: [Double]

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.uint8() else { return nil }
        if flags & 0x01 != 0 {
            guard let v = r.uint16() else { return nil }
            bpm = Int(v)
        } else {
            guard let v = r.uint8() else { return nil }
            bpm = Int(v)
        }
        // Bits 1-2: 0b10 contact supported but not detected, 0b11 detected; 0b0x not supported.
        skinContact = flags & 0x04 != 0 ? flags & 0x02 != 0 : nil
        if flags & 0x08 != 0 {
            guard let v = r.uint16() else { return nil }
            energyExpended = Int(v)
        } else {
            energyExpended = nil
        }
        var rr: [Double] = []
        if flags & 0x10 != 0 {
            while let v = r.uint16() { rr.append(Double(v) / 1024) }
        }
        rrIntervals = rr
    }
}

/// CSC Measurement (0x2A5B), from a speed sensor, a cadence sensor or a combined one.
struct CSCMeasurement: Equatable, Sendable {
    /// Event time in 1/1024 s.
    var wheel: RevolutionData?
    /// Crank revolutions are 16-bit here (they wrap at 65,536); event time in 1/1024 s.
    var crank: RevolutionData?

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.uint8() else { return nil }
        if flags & 0x01 != 0 {
            guard let revs = r.uint32(), let time = r.uint16() else { return nil }
            wheel = RevolutionData(revolutions: revs, eventTime: time)
        }
        if flags & 0x02 != 0 {
            guard let revs = r.uint16(), let time = r.uint16() else { return nil }
            crank = RevolutionData(revolutions: UInt32(revs), eventTime: time)
        }
    }
}

/// Cycling Power Measurement (0x2A63), from a power meter or a smart trainer's power service.
struct CyclingPowerMeasurement: Equatable, Sendable {
    /// Watts, signed: some meters report a little below zero when back-pedalling.
    var power: Int
    /// The share of the power from one pedal, in percent (sent in 1/2 %). Which pedal is a flag Headwind ignores.
    var pedalBalance: Double?
    /// Event time in 1/2048 s, not 1/1024 s as on a speed sensor.
    var wheel: RevolutionData?
    /// 16-bit crank revolutions, event time in 1/1024 s: the cadence a power meter gives.
    var crank: RevolutionData?
    /// Kilojoules since the meter was reset.
    var accumulatedEnergy: Int?

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.uint16(), let watts = r.int16() else { return nil }
        power = Int(watts)
        if flags & 0x0001 != 0 {
            guard let v = r.uint8() else { return nil }
            pedalBalance = Double(v) / 2
        }
        if flags & 0x0004 != 0, !r.skip(2) { return nil }            // accumulated torque
        if flags & 0x0010 != 0 {
            guard let revs = r.uint32(), let time = r.uint16() else { return nil }
            wheel = RevolutionData(revolutions: revs, eventTime: time)
        }
        if flags & 0x0020 != 0 {
            guard let revs = r.uint16(), let time = r.uint16() else { return nil }
            crank = RevolutionData(revolutions: UInt32(revs), eventTime: time)
        }
        if flags & 0x0040 != 0, !r.skip(4) { return nil }            // extreme force magnitudes
        if flags & 0x0080 != 0, !r.skip(4) { return nil }            // extreme torque magnitudes
        if flags & 0x0100 != 0, !r.skip(3) { return nil }            // extreme angles (two 12-bit values)
        if flags & 0x0200 != 0, !r.skip(2) { return nil }            // top dead spot angle
        if flags & 0x0400 != 0, !r.skip(2) { return nil }            // bottom dead spot angle
        if flags & 0x0800 != 0 {
            guard let v = r.uint16() else { return nil }
            accumulatedEnergy = Int(v)
        }
    }
}

/// Indoor Bike Data (0x2AD2), the Fitness Machine service's reading from a smart trainer. A trainer may split one
/// reading over several notifications ("More Data"), so every field is optional: keep the latest of each.
struct IndoorBikeData: Equatable, Sendable {
    /// m/s (sent in 0.01 km/h).
    var speed: Double?
    var averageSpeed: Double?
    /// rpm (sent in 0.5 rpm).
    var cadence: Double?
    var averageCadence: Double?
    /// Metres since the trainer's session started.
    var totalDistance: Int?
    var resistanceLevel: Int?
    /// Watts.
    var power: Int?
    var averagePower: Int?
    /// Kilocalories.
    var totalEnergy: Int?
    var heartRate: Int?
    /// Seconds.
    var elapsedTime: Int?
    var remainingTime: Int?

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.uint16() else { return nil }
        func has(_ bit: Int) -> Bool { flags & (1 << bit) != 0 }
        func kmh(_ v: UInt16) -> Double { Double(v) / 100 / 3.6 }

        // Bit 0 is inverted: clear means instantaneous speed is present, set means "more data follows" without it.
        if !has(0) {
            guard let v = r.uint16() else { return nil }
            speed = kmh(v)
        }
        if has(1) {
            guard let v = r.uint16() else { return nil }
            averageSpeed = kmh(v)
        }
        if has(2) {
            guard let v = r.uint16() else { return nil }
            cadence = Double(v) / 2
        }
        if has(3) {
            guard let v = r.uint16() else { return nil }
            averageCadence = Double(v) / 2
        }
        if has(4) {
            guard let v = r.uint24() else { return nil }
            totalDistance = Int(v)
        }
        if has(5) {
            guard let v = r.int16() else { return nil }
            resistanceLevel = Int(v)
        }
        if has(6) {
            guard let v = r.int16() else { return nil }
            power = Int(v)
        }
        if has(7) {
            guard let v = r.int16() else { return nil }
            averagePower = Int(v)
        }
        if has(8) {
            // Total energy, then energy per hour (UInt16) and per minute (UInt8). 0xFFFF means "not available".
            guard let total = r.uint16(), r.skip(3) else { return nil }
            totalEnergy = total == 0xFFFF ? nil : Int(total)
        }
        if has(9) {
            guard let v = r.uint8() else { return nil }
            heartRate = Int(v)
        }
        if has(10), !r.skip(1) { return nil }                       // metabolic equivalent
        if has(11) {
            guard let v = r.uint16() else { return nil }
            elapsedTime = Int(v)
        }
        if has(12) {
            guard let v = r.uint16() else { return nil }
            remainingTime = Int(v)
        }
    }
}

/// Battery Level (0x2A19): one byte, a percentage.
enum BatteryLevel {
    static func percent(_ data: Data) -> Int? {
        var r = ByteReader(data)
        guard let v = r.uint8(), v <= 100 else { return nil }
        return Int(v)
    }
}
