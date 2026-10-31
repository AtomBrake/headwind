import Foundation

/// The Bluetooth LE sensors Headwind reads on the iPhone, and the standard GATT values they send, parsed as plain Swift so it's unit-tested
/// without a device. CoreBluetooth itself is in `Headwind/Sensors/SensorManager.swift`; this file only knows bytes.
///
/// Every multi-byte field is little-endian, as the Bluetooth SIG's specifications have them.
enum GATT {
    // Services
    static let heartRateService: UInt16 = 0x180D
    static let cyclingSpeedCadenceService: UInt16 = 0x1816
    static let cyclingPowerService: UInt16 = 0x1818
    static let fitnessMachineService: UInt16 = 0x1826
    static let batteryService: UInt16 = 0x180F

    // Characteristics
    static let heartRateMeasurement: UInt16 = 0x2A37
    static let cscMeasurement: UInt16 = 0x2A5B
    static let cyclingPowerMeasurement: UInt16 = 0x2A63
    static let indoorBikeData: UInt16 = 0x2AD2
    static let batteryLevel: UInt16 = 0x2A19

    /// The characteristics that stream readings, subscribed to on every sensor that has them.
    static let measurements: [UInt16] = [heartRateMeasurement, cscMeasurement, cyclingPowerMeasurement, indoorBikeData]
}

/// What a sensor is, from the services it offers. A device that offers several (a smart trainer is usually a power meter and a speed sensor too)
/// is the first of trainer, power meter, speed and cadence, heart rate; its readings come from every service it has, whatever its kind.
enum SensorKind: String, Codable, CaseIterable, Identifiable, Sendable {
    case trainer, power, speedCadence, heartRate

    var id: Self { self }

    var service: UInt16 {
        switch self {
        case .heartRate: GATT.heartRateService
        case .speedCadence: GATT.cyclingSpeedCadenceService
        case .power: GATT.cyclingPowerService
        case .trainer: GATT.fitnessMachineService
        }
    }

    var title: String {
        switch self {
        case .heartRate: "Heart rate"
        case .speedCadence: "Speed and cadence"
        case .power: "Power meter"
        case .trainer: "Smart trainer"
        }
    }

    var systemImage: String {
        switch self {
        case .heartRate: "heart.fill"
        case .speedCadence: "speedometer"
        case .power: "bolt.fill"
        case .trainer: "figure.indoor.cycle"
        }
    }

    /// The services scanned for: only sensors offering one of these are found.
    static var services: [UInt16] { allCases.map(\.service) }

    /// The kind of a device offering these services (16-bit UUIDs), or nil if it offers none Headwind reads.
    static func main(of services: some Sequence<UInt16>) -> SensorKind? {
        let offered = Set(services)
        return allCases.first { offered.contains($0.service) }
    }
}

/// Reads a GATT value field by field, failing (nil) rather than reading past the end of a short packet.
struct ByteReader {
    private let bytes: [UInt8]
    private var index = 0

    init(_ data: Data) { bytes = [UInt8](data) }

    var remaining: Int { bytes.count - index }

    mutating func u8() -> UInt8? {
        guard remaining >= 1 else { return nil }
        defer { index += 1 }
        return bytes[index]
    }

    mutating func u16() -> UInt16? {
        guard remaining >= 2 else { return nil }
        defer { index += 2 }
        return UInt16(bytes[index]) | UInt16(bytes[index + 1]) << 8
    }

    mutating func s16() -> Int16? { u16().map { Int16(bitPattern: $0) } }

    mutating func u24() -> UInt32? {
        guard remaining >= 3 else { return nil }
        defer { index += 3 }
        return UInt32(bytes[index]) | UInt32(bytes[index + 1]) << 8 | UInt32(bytes[index + 2]) << 16
    }

    mutating func u32() -> UInt32? {
        guard remaining >= 4 else { return nil }
        defer { index += 4 }
        return UInt32(bytes[index]) | UInt32(bytes[index + 1]) << 8 | UInt32(bytes[index + 2]) << 16 | UInt32(bytes[index + 3]) << 24
    }

    mutating func skip(_ count: Int) -> Bool {
        guard remaining >= count else { return false }
        index += count
        return true
    }
}

/// A cumulative revolution count and the time of the last revolution, as a wheel or crank sensor sends them. The time wraps every 64 s
/// (1/1024 s ticks; a power meter's wheel uses 1/2048 s, so 32 s), and the counts wrap too: see `RevolutionRate`.
struct Revolutions: Equatable, Sendable {
    var count: UInt32
    var eventTime: UInt16
}

/// Heart Rate Measurement (0x2A37): a flags byte, then the rate as 8 or 16 bits. Energy expended and RR intervals may follow; they're not used.
struct HeartRateMeasurement: Equatable, Sendable {
    var bpm: Int
    /// Whether the strap is touching skin, for straps that can tell (nil for those that can't).
    var contactDetected: Bool?

    init(bpm: Int, contactDetected: Bool? = nil) {
        self.bpm = bpm
        self.contactDetected = contactDetected
    }

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.u8() else { return nil }
        let rate: Int? = flags & 0x01 != 0 ? r.u16().map(Int.init) : r.u8().map(Int.init)
        guard let rate else { return nil }
        bpm = rate
        contactDetected = flags & 0x04 != 0 ? flags & 0x02 != 0 : nil
    }

    /// A reading worth recording: a strap lying on the table sends 0, or says it has no contact.
    var isValid: Bool { bpm > 0 && contactDetected != false }
}

/// CSC Measurement (0x2A5B): wheel revolutions (32-bit) and crank revolutions (16-bit), each with its last event time in 1/1024 s, each
/// present by its flag bit. Speed and cadence come from the difference between two readings (`RevolutionRate`).
struct CSCMeasurement: Equatable, Sendable {
    var wheel: Revolutions?
    var crank: Revolutions?

    init(wheel: Revolutions? = nil, crank: Revolutions? = nil) {
        self.wheel = wheel
        self.crank = crank
    }

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.u8() else { return nil }
        if flags & 0x01 != 0 {
            guard let count = r.u32(), let time = r.u16() else { return nil }
            wheel = Revolutions(count: count, eventTime: time)
        }
        if flags & 0x02 != 0 {
            guard let count = r.u16(), let time = r.u16() else { return nil }
            crank = Revolutions(count: UInt32(count), eventTime: time)
        }
    }
}

/// Cycling Power Measurement (0x2A63): 16 bits of flags, instantaneous power as signed 16-bit watts, then optional fields in a fixed order.
/// Only those up to the crank revolution data are read (for cadence, which most power meters send), skipping the ones before it.
struct CyclingPowerMeasurement: Equatable, Sendable {
    var power: Int
    /// Wheel revolutions, with the event time in 1/2048 s (not 1/1024 s as in CSC).
    var wheel: Revolutions?
    /// Crank revolutions, the event time in 1/1024 s.
    var crank: Revolutions?

    init(power: Int, wheel: Revolutions? = nil, crank: Revolutions? = nil) {
        self.power = power
        self.wheel = wheel
        self.crank = crank
    }

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.u16(), let watts = r.s16() else { return nil }
        power = Int(watts)
        if flags & 0x0001 != 0, !r.skip(1) { return nil }        // pedal power balance
        if flags & 0x0004 != 0, !r.skip(2) { return nil }        // accumulated torque
        if flags & 0x0010 != 0 {
            guard let count = r.u32(), let time = r.u16() else { return nil }
            wheel = Revolutions(count: count, eventTime: time)
        }
        if flags & 0x0020 != 0 {
            guard let count = r.u16(), let time = r.u16() else { return nil }
            crank = Revolutions(count: UInt32(count), eventTime: time)
        }
    }
}

/// Indoor Bike Data (0x2AD2), a smart trainer's readings under Fitness Machine (0x1826): 16 bits of flags, then each field present by its bit.
/// Bit 0 is "more data", and inverted: the instantaneous speed is there when it's 0. Trainers may split one reading over several packets.
struct IndoorBikeData: Equatable, Sendable {
    /// m/s (sent as 0.01 km/h).
    var speed: Double?
    /// rpm (sent in 0.5 rpm).
    var cadence: Double?
    /// Metres since the trainer started counting.
    var distance: Double?
    var resistance: Int?
    var power: Int?
    /// From a strap the trainer is paired with, if any.
    var heartRate: Int?
    var elapsed: Int?

    init(speed: Double? = nil, cadence: Double? = nil, distance: Double? = nil, resistance: Int? = nil, power: Int? = nil,
         heartRate: Int? = nil, elapsed: Int? = nil) {
        self.speed = speed
        self.cadence = cadence
        self.distance = distance
        self.resistance = resistance
        self.power = power
        self.heartRate = heartRate
        self.elapsed = elapsed
    }

    init?(_ data: Data) {
        var r = ByteReader(data)
        guard let flags = r.u16() else { return nil }
        func has(_ bit: Int) -> Bool { flags & (1 << bit) != 0 }
        if !has(0) {
            guard let v = r.u16() else { return nil }
            speed = Double(v) / 100 / 3.6
        }
        if has(1), !r.skip(2) { return nil }                       // average speed
        if has(2) {
            guard let v = r.u16() else { return nil }
            cadence = Double(v) / 2
        }
        if has(3), !r.skip(2) { return nil }                       // average cadence
        if has(4) {
            guard let v = r.u24() else { return nil }
            distance = Double(v)
        }
        if has(5) {
            guard let v = r.s16() else { return nil }
            resistance = Int(v)
        }
        if has(6) {
            guard let v = r.s16() else { return nil }
            power = Int(v)
        }
        if has(7), !r.skip(2) { return nil }                       // average power
        if has(8), !r.skip(5) { return nil }                       // energy: total, per hour, per minute
        if has(9) {
            guard let v = r.u8() else { return nil }
            heartRate = Int(v)
        }
        if has(10), !r.skip(1) { return nil }                      // metabolic equivalent
        if has(11) {
            guard let v = r.u16() else { return nil }
            elapsed = Int(v)
        }
    }
}

/// Battery Level (0x2A19): one byte, 0–100 %.
enum BatteryLevel {
    static func parse(_ data: Data) -> Int? {
        guard let first = data.first, first <= 100 else { return nil }
        return Int(first)
    }
}
