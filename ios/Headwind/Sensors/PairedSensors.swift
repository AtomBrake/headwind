import Foundation

/// What a sensor is, by the GATT service it offers. One sensor can be several: a power meter that gives cadence, a trainer that is also
/// a power meter.
enum SensorKind: String, Codable, CaseIterable, Sendable {
    case heartRate
    case speedCadence
    case power
    case trainer

    init?(service: UInt16) {
        switch service {
        case GATT.heartRateService: self = .heartRate
        case GATT.cyclingSpeedAndCadenceService: self = .speedCadence
        case GATT.cyclingPowerService: self = .power
        case GATT.fitnessMachineService: self = .trainer
        default: return nil
        }
    }

    var service: UInt16 {
        switch self {
        case .heartRate: GATT.heartRateService
        case .speedCadence: GATT.cyclingSpeedAndCadenceService
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

    /// The kinds a set of advertised or discovered service numbers stands for.
    static func kinds(of services: [UInt16]) -> Set<SensorKind> { Set(services.compactMap(SensorKind.init(service:))) }
}

/// A sensor paired on the Sensors screen. Remembered by its `CBPeripheral.identifier`, which CoreBluetooth makes up per phone:
/// a sensor has to be paired again on another iPhone.
struct PairedSensor: Codable, Equatable, Identifiable, Sendable {
    var id: UUID
    var name: String
    var kinds: Set<SensorKind>
}

/// The paired sensors, kept in UserDefaults in the order they were paired.
struct PairedSensors {
    var defaults: UserDefaults = .standard
    static let key = "paired-sensors"

    var all: [PairedSensor] {
        get {
            guard let data = defaults.data(forKey: Self.key) else { return [] }
            return (try? JSONDecoder().decode([PairedSensor].self, from: data)) ?? []
        }
        nonmutating set {
            defaults.set(try? JSONEncoder().encode(newValue), forKey: Self.key)
        }
    }

    /// Adds the sensor, or updates its name and kinds if it's already paired (it keeps its place).
    func remember(_ sensor: PairedSensor) {
        var list = all
        if let i = list.firstIndex(where: { $0.id == sensor.id }) { list[i] = sensor } else { list.append(sensor) }
        all = list
    }

    func forget(_ id: UUID) {
        all = all.filter { $0.id != id }
    }
}

extension GATT {
    /// The characteristics to read on a service the sensor offers, or nil for one Headwind doesn't use. On a trainer, Indoor Bike
    /// Data gives power, cadence and speed, so the Cycling Power and Speed and Cadence services many trainers offer as well are
    /// left alone rather than read twice.
    static func characteristics(toRead service: UInt16, onTrainer: Bool) -> [UInt16]? {
        switch service {
        case heartRateService: [heartRateMeasurement]
        case cyclingSpeedAndCadenceService: onTrainer ? nil : [cscMeasurement]
        case cyclingPowerService: onTrainer ? nil : [cyclingPowerMeasurement]
        case fitnessMachineService: [indoorBikeData]
        case batteryService: [batteryLevel]
        default: nil
        }
    }
}
