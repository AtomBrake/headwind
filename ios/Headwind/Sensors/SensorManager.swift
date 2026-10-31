@preconcurrency import CoreBluetooth
import Foundation
import Observation

/// Why the sensors are wanted connected. While any is held they're connected (and reconnected when one drops); with none, they're let go, so
/// neither the phone nor the sensors spend battery on a link nothing reads.
enum SensorUse: Hashable, Sendable {
    /// The Sensors screen is open: scan too.
    case sensorsScreen
    /// The Record screen is showing: connect before Start, so the readings are there from the first second.
    case recordScreen
    case recording
}

/// What `PhoneRideRecorder` needs from the sensors, so the tests can stand in for Bluetooth.
@MainActor
protocol SensorFeed: AnyObject {
    var hasPaired: Bool { get }
    func readings(at date: Date) -> SensorReadings
    func use(_ use: SensorUse)
    func stopUsing(_ use: SensorUse)
    /// Called after each reading arrives, so a timed session keeps taking its samples in the background, where only Bluetooth wakes the app.
    var onReading: (() -> Void)? { get set }
}

/// Bluetooth LE sensors on the iPhone: heart rate straps (0x180D), speed and cadence sensors (0x1816), power meters (0x1818) and smart trainers
/// (Fitness Machine, 0x1826). Scans for those four services only: on the Sensors screen, and quietly while a paired one can't be found by
/// identifier. Connects to the paired ones by identifier (`retrievePeripherals`, or `retrieveConnectedPeripherals` for one another app has
/// connected), and reconnects by itself when one drops mid-ride: a pending connection never times out, so iOS completes it when the sensor is
/// back in range. On a trainer only Indoor Bike Data is read, not the Cycling Power and Speed and Cadence services it may offer too, so
/// nothing is counted twice. The parsing and arithmetic are `SensorChannel` and `SensorReadings`, in `Shared/`.
///
/// The central is made only when it's needed (the Sensors screen opens, or there are paired sensors and Bluetooth was allowed), because
/// making one is what asks for permission. Its restore identifier lets iOS hand back the connections if it ends the app mid-ride.
@MainActor
@Observable
final class SensorManager: NSObject, SensorFeed {
    /// A sensor paired on this phone, remembered by its `CBPeripheral.identifier`, which is per phone: another iPhone pairs it again.
    struct Paired: Codable, Equatable, Identifiable, Sendable {
        var id: UUID
        var name: String
        var kind: SensorKind
    }

    /// A sensor found by the scan, not yet paired.
    struct Found: Equatable, Identifiable, Sendable {
        var id: UUID
        var name: String
        var kind: SensorKind
        /// dBm.
        var rssi: Int
    }

    enum Link: Equatable, Sendable {
        /// Not connected, and not trying (nothing needs it, or Bluetooth is off).
        case idle
        /// Trying: connects as soon as the sensor is awake and in range.
        case connecting
        case connected
    }

    /// Bluetooth on this phone, as far as Headwind may know.
    enum Radio: Equatable, Sendable {
        /// Headwind hasn't asked for Bluetooth yet.
        case notAsked
        case starting
        case on
        case off
        case denied
        case unsupported
    }

    private(set) var paired: [Paired]
    private(set) var found: [Found] = []
    private(set) var links: [UUID: Link] = [:]
    private(set) var battery: [UUID: Int] = [:]
    private(set) var radio: Radio
    private(set) var isScanning = false
    /// The wheel's circumference for a wheel sensor's speed and distance.
    private(set) var wheelMillimetres: Int

    @ObservationIgnored var onReading: (() -> Void)?
    @ObservationIgnored private var channels: [UUID: SensorChannel] = [:]
    @ObservationIgnored private var central: CBCentralManager?
    /// CoreBluetooth drops a peripheral nothing holds on to, connection and all.
    @ObservationIgnored private var peripherals: [UUID: CBPeripheral] = [:]
    @ObservationIgnored private var foundPeripherals: [UUID: CBPeripheral] = [:]
    @ObservationIgnored private var uses: Set<SensorUse> = []
    @ObservationIgnored private var release: Task<Void, Never>?
    /// What the central is scanning with now: nil when it isn't, true when it reports every advertisement (signal strength on the Sensors
    /// screen), false when only the first (looking for a paired sensor iOS has forgotten).
    @ObservationIgnored private var scanMode: Bool?
    private let defaults: UserDefaults
    private let wheel: WheelSize

    /// How long the sensors stay connected once nothing needs them, so going from the Record tab to the Sensors screen (one lets go
    /// before the other takes hold) or another tab and back doesn't drop them.
    static let releaseDelay: Duration = .seconds(10)
    private static let pairedKey = "sensors-paired"
    private static let restoreID = "io.github.atombrake.headwind.sensors"
    private static let scanServices = SensorKind.services.map(\.cbuuid)
    private static let services = (SensorKind.services + [GATT.batteryService]).map(\.cbuuid)

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        wheel = WheelSize(defaults: defaults)
        paired = (defaults.data(forKey: Self.pairedKey)).flatMap { try? JSONDecoder().decode([Paired].self, from: $0) } ?? []
        wheelMillimetres = WheelSize(defaults: defaults).millimetres
        radio = Self.radio(CBManager.authorization)
        super.init()
        // Made at launch only when there's something to reconnect to and Bluetooth was allowed: iOS restores the connections of a ride it
        // ended only into a central made at launch, and making one before that would ask for Bluetooth before the Sensors screen does.
        if !paired.isEmpty, CBManager.authorization == .allowedAlways { makeCentral() }
    }

    var hasPaired: Bool { !paired.isEmpty }
    var connectedCount: Int { paired.filter { links[$0.id] == .connected }.count }

    /// All the paired sensors' readings as one (`SensorReadings.combine`).
    func readings(at date: Date = .now) -> SensorReadings {
        SensorReadings.combine(paired.compactMap { sensor in
            channels[sensor.id].map { .init(kind: sensor.kind, id: sensor.id, readings: $0.readings(at: date, wheelCircumference: wheelMetres)) }
        })
    }

    /// One sensor's own readings, for its row on the Sensors screen.
    func readings(of id: UUID, at date: Date = .now) -> SensorReadings? {
        channels[id]?.readings(at: date, wheelCircumference: wheelMetres)
    }

    func use(_ use: SensorUse) {
        uses.insert(use)
        if use == .sensorsScreen || (!paired.isEmpty && CBManager.authorization == .allowedAlways) { makeCentral() }
        refresh()
    }

    func stopUsing(_ use: SensorUse) {
        uses.remove(use)
        refresh()
    }

    func pair(_ sensor: Found) {
        guard !paired.contains(where: { $0.id == sensor.id }) else { return }
        paired.append(Paired(id: sensor.id, name: sensor.name, kind: sensor.kind))
        save()
        found.removeAll { $0.id == sensor.id }
        if let p = foundPeripherals.removeValue(forKey: sensor.id) { peripherals[sensor.id] = p }
        connect(sensor.id)
    }

    func forget(_ id: UUID) {
        paired.removeAll { $0.id == id }
        save()
        if let p = peripherals.removeValue(forKey: id), p.state != .disconnected { central?.cancelPeripheralConnection(p) }
        channels[id] = nil
        links[id] = nil
        battery[id] = nil
    }

    func setWheel(millimetres: Int) {
        wheel.millimetres = millimetres
        wheelMillimetres = wheel.millimetres
    }

    private var wheelMetres: Double { Double(wheelMillimetres) / 1000 }

    private func save() {
        if let data = try? JSONEncoder().encode(paired) { defaults.set(data, forKey: Self.pairedKey) }
    }

    private func makeCentral() {
        guard central == nil else { return }
        radio = .starting
        // No system alert when Bluetooth is off: the Sensors screen says so itself, and launch is no time for one.
        central = CBCentralManager(delegate: self, queue: nil, options: [
            CBCentralManagerOptionRestoreIdentifierKey: Self.restoreID,
            CBCentralManagerOptionShowPowerAlertKey: false,
        ])
    }

    /// Connect the paired sensors while anything needs them, and let them go when nothing does; scan as `updateScan` says.
    private func refresh() {
        guard let central, central.state == .poweredOn else { return }
        release?.cancel()
        release = nil
        if uses.isEmpty {
            release = Task { [weak self] in
                try? await Task.sleep(for: Self.releaseDelay)
                guard !Task.isCancelled else { return }
                self?.disconnectAll()
            }
        } else {
            for sensor in paired { connect(sensor.id) }
        }
        updateScan()
    }

    /// Scans with every advertisement while the Sensors screen is open, for new sensors and their signal; otherwise, while the sensors are
    /// wanted and a paired one couldn't be found by identifier (iOS forgets a peripheral it hasn't seen for a while), scans for its first
    /// advertisement only. Only for the four services: that's also what lets it scan in the background.
    private func updateScan() {
        guard let central, central.state == .poweredOn else {
            scanMode = nil
            isScanning = false
            return
        }
        let screen = uses.contains(.sensorsScreen)
        let missing = !uses.isEmpty && paired.contains { peripherals[$0.id] == nil }
        let wanted: Bool? = screen ? true : missing ? false : nil
        if wanted != scanMode {
            if central.isScanning { central.stopScan() }
            if let wanted {
                central.scanForPeripherals(withServices: Self.scanServices, options: [CBCentralManagerScanOptionAllowDuplicatesKey: wanted])
            }
            scanMode = wanted
        }
        if isScanning != screen { isScanning = screen }
        if !screen, !found.isEmpty || !foundPeripherals.isEmpty {
            found = []
            foundPeripherals = [:]
        }
    }

    private func disconnectAll() {
        guard uses.isEmpty, let central else { return }
        for (id, p) in peripherals {
            if p.state != .disconnected { central.cancelPeripheralConnection(p) }
            links[id] = .idle
        }
    }

    private func connect(_ id: UUID) {
        guard let central, central.state == .poweredOn else { return }
        guard let peripheral = peripherals[id] ?? central.retrievePeripherals(withIdentifiers: [id]).first
                ?? central.retrieveConnectedPeripherals(withServices: Self.scanServices).first(where: { $0.identifier == id }) else {
            links[id] = .idle    // iOS has forgotten it: `updateScan` looks for it
            return
        }
        peripherals[id] = peripheral
        peripheral.delegate = self
        switch peripheral.state {
        case .connected:
            links[id] = .connected
            if peripheral.services == nil { peripheral.discoverServices(Self.services) }
        case .connecting:
            links[id] = .connecting
        default:
            links[id] = .connecting
            central.connect(peripheral)
        }
    }

    /// After a drop or a failed attempt: try again while it's wanted. iOS keeps the attempt open until the sensor is back.
    private func reconnect(_ peripheral: CBPeripheral, after delay: Duration = .zero) {
        let id = peripheral.identifier
        guard paired.contains(where: { $0.id == id }) else {
            links[id] = nil
            return
        }
        peripherals[id] = peripherals[id] ?? peripheral
        links[id] = .idle
        guard !uses.isEmpty else { return }
        links[id] = .connecting
        Task { [weak self] in
            if delay > .zero { try? await Task.sleep(for: delay) }
            guard let self, !self.uses.isEmpty, self.paired.contains(where: { $0.id == id }), let central = self.central,
                  central.state == .poweredOn, let p = self.peripherals[id], p.state == .disconnected else { return }
            central.connect(p)
        }
    }

    private static func radio(_ authorization: CBManagerAuthorization) -> Radio {
        switch authorization {
        case .allowedAlways: .starting
        case .denied, .restricted: .denied
        default: .notAsked
        }
    }
}

extension SensorManager: @preconcurrency CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn: radio = .on
        case .poweredOff: radio = .off
        case .unauthorized: radio = .denied
        case .unsupported: radio = .unsupported
        default: radio = .starting
        }
        if central.state == .poweredOn {
            refresh()
        } else {
            for id in links.keys { links[id] = .idle }
            scanMode = nil
            isScanning = false
            found = []
            foundPeripherals = [:]
        }
    }

    /// iOS ended the app while sensors were connected, and has started it again for them: take the connections back.
    func centralManager(_ central: CBCentralManager, willRestoreState dict: [String: Any]) {
        for p in dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? [] where paired.contains(where: { $0.id == p.identifier }) {
            peripherals[p.identifier] = p
            p.delegate = self
            links[p.identifier] = p.state == .connected ? .connected : .connecting
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String: Any],
                        rssi RSSI: NSNumber) {
        let id = peripheral.identifier
        if paired.contains(where: { $0.id == id }) {
            // A paired sensor iOS had forgotten (so it couldn't be retrieved by identifier): connect it now.
            if peripherals[id] == nil {
                peripherals[id] = peripheral
                if !uses.isEmpty { connect(id) }
                updateScan()
            }
            return
        }
        guard uses.contains(.sensorsScreen) else { return }
        let advertised = (advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? [])
            + (advertisementData[CBAdvertisementDataOverflowServiceUUIDsKey] as? [CBUUID] ?? [])
        guard let kind = SensorKind.main(of: advertised.compactMap(\.short)) else { return }
        let name = peripheral.name ?? advertisementData[CBAdvertisementDataLocalNameKey] as? String ?? kind.title
        let rssi = RSSI.intValue    // 127: not known this time
        if let i = found.firstIndex(where: { $0.id == id }) {
            // Duplicates arrive several times a second: only redraw for a real change.
            if rssi != 127, abs(found[i].rssi - rssi) >= 4 { found[i].rssi = rssi }
            if found[i].name != name { found[i].name = name }
        } else {
            found.append(Found(id: id, name: name, kind: kind, rssi: rssi == 127 ? -100 : rssi))
            foundPeripherals[id] = peripheral
        }
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        let id = peripheral.identifier
        guard paired.contains(where: { $0.id == id }), !uses.isEmpty else {
            central.cancelPeripheralConnection(peripheral)
            return
        }
        links[id] = .connected
        peripheral.delegate = self
        peripheral.discoverServices(Self.services)
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: (any Error)?) {
        reconnect(peripheral, after: .seconds(2))
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: (any Error)?) {
        reconnect(peripheral)
    }
}

extension SensorManager: @preconcurrency CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: (any Error)?) {
        let services = peripheral.services ?? []
        let offered = services.compactMap { $0.uuid.short }
        // A trainer's Indoor Bike Data has its power, cadence and speed: its Cycling Power and Speed and Cadence services aren't read too.
        let onTrainer = SensorKind.kinds(of: offered).contains(.trainer)
        for service in services {
            guard let number = service.uuid.short, let wanted = GATT.characteristics(toRead: number, onTrainer: onTrainer) else { continue }
            peripheral.discoverCharacteristics(wanted.map(\.cbuuid), for: service)
        }
        // What it really offers can say more than its advertisement did (a trainer that advertised only its power).
        if let kind = SensorKind.main(of: offered),
           let i = paired.firstIndex(where: { $0.id == peripheral.identifier }), paired[i].kind != kind {
            paired[i].kind = kind
            save()
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: (any Error)?) {
        for characteristic in service.characteristics ?? [] {
            guard let code = characteristic.uuid.short else { continue }
            if GATT.measurements.contains(code) {
                peripheral.setNotifyValue(true, for: characteristic)
            } else if code == GATT.batteryLevel {
                peripheral.readValue(for: characteristic)
                if characteristic.properties.contains(.notify) { peripheral.setNotifyValue(true, for: characteristic) }
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: (any Error)?) {
        guard error == nil, let data = characteristic.value, let code = characteristic.uuid.short else { return }
        let id = peripheral.identifier
        if code == GATT.batteryLevel {
            if let level = BatteryLevel.parse(data), battery[id] != level { battery[id] = level }
            return
        }
        var channel = channels[id] ?? SensorChannel()
        guard channel.receive(code, data, at: Date()) else { return }
        channels[id] = channel
        onReading?()
    }
}

extension UInt16 {
    fileprivate var cbuuid: CBUUID { CBUUID(string: String(format: "%04X", self)) }
}

extension CBUUID {
    /// The 16-bit form of a Bluetooth SIG UUID, whether CoreBluetooth gives it short or in full on the base UUID.
    fileprivate var short: UInt16? {
        let d = [UInt8](data)
        if d.count == 2 { return UInt16(d[0]) << 8 | UInt16(d[1]) }
        let base: [UInt8] = [0x00, 0x00, 0x10, 0x00, 0x80, 0x00, 0x00, 0x80, 0x5F, 0x9B, 0x34, 0xFB]
        if d.count == 16, d[0] == 0, d[1] == 0, Array(d[4...]) == base { return UInt16(d[2]) << 8 | UInt16(d[3]) }
        return nil
    }
}
