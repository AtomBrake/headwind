import CoreBluetooth
import Foundation
import Observation

/// Bluetooth LE sensors on the iPhone: heart-rate straps, speed and cadence sensors, power meters and smart trainers, through their
/// standard GATT services (the Watch has its own, through HealthKit). Scans only for those four services, connects to the paired
/// sensors by identifier before scanning for any, and reconnects on its own when one drops mid-ride. What they send is combined by a
/// `SensorHub`, read with `readings()`.
///
/// Nothing touches Bluetooth until something `hold`s the manager: making a `CBCentralManager` is what asks for permission, and that
/// should be on the Sensors screen, not at launch. The one exception is a launch with paired sensors and Bluetooth already allowed,
/// when the central is made at once for state restoration: iOS hands a relaunched app its connections only through a central made
/// at launch with the same restore identifier.
///
/// Connections are kept while anything holds the manager (the Record screen showing, a recording, the Sensors screen) and dropped
/// once nothing does, so a strap isn't kept awake all day.
@MainActor
@Observable
final class SensorManager {
    /// What wants the sensors connected.
    enum Use: Hashable, Sendable {
        case recordScreen, recording, sensorsScreen
    }

    enum Connection: Sendable {
        case connecting, connected
    }

    /// A sensor seen by a scan for new ones, not paired.
    struct Found: Identifiable, Equatable, Sendable {
        var id: UUID
        var name: String
        var kinds: Set<SensorKind>
        /// dBm.
        var signal: Int
    }

    static let restoreIdentifier = "io.github.atombrake.headwind.sensors"
    static let scannedServices = GATT.sensorServices.map { CBUUID(string: GATT.uuidString($0)) }

    private(set) var paired: [PairedSensor]
    /// Found by `scanForNew()`, in the order they were first seen.
    private(set) var found: [Found] = []
    /// Paired sensors being connected or connected; one not in here is disconnected.
    private(set) var connections: [UUID: Connection] = [:]
    /// Percent, from the Battery Service, for the sensors that have one.
    private(set) var batteries: [UUID: Int] = [:]
    /// `.unknown` until something has held the manager.
    private(set) var bluetoothState: CBManagerState = .unknown
    private(set) var isScanningForNew = false

    /// Whether Bluetooth has been allowed, asked for, or refused; reading it doesn't ask.
    var authorization: CBManagerAuthorization { CBManager.authorization }

    /// Metres, for speed and distance from a wheel-speed sensor.
    var wheelCircumference: Double {
        get { hub.wheelCircumference }
        set { hub.wheelCircumference = newValue }
    }

    // The hub changes with every notification (several a second per sensor): not observed. Readers poll `readings()`.
    @ObservationIgnored private var hub = SensorHub()
    private let store: PairedSensors
    private let link = BluetoothLink()
    @ObservationIgnored private var central: CBCentralManager?
    /// Every peripheral handed over by CoreBluetooth for a paired sensor, kept so its connection isn't dropped with the object.
    @ObservationIgnored private var peripherals: [UUID: CBPeripheral] = [:]
    @ObservationIgnored private var uses: Set<Use> = []
    /// What the central is scanning with now: nil when it isn't, otherwise whether it reports every advertisement (for signal
    /// strength on the Sensors screen) or only the first.
    @ObservationIgnored private var scanning: Bool?

    init(store: PairedSensors = PairedSensors()) {
        self.store = store
        paired = store.all
        link.owner = self
        if !paired.isEmpty, CBManager.authorization == .allowedAlways { startBluetooth() }
    }

    /// Every sensor's readings combined, or one sensor's alone.
    func readings(of sensor: UUID? = nil) -> SensorReadings {
        hub.readings(at: ProcessInfo.processInfo.systemUptime, of: sensor)
    }

    // MARK: Holding

    /// Connects the paired sensors, and keeps them connected until every use is released. `.sensorsScreen` starts Bluetooth even
    /// with nothing paired, which asks for permission the first time.
    func hold(_ use: Use) {
        uses.insert(use)
        if use == .sensorsScreen || !paired.isEmpty { startBluetooth() }
        connectPaired()
    }

    func release(_ use: Use) {
        uses.remove(use)
        if use == .sensorsScreen {
            isScanningForNew = false
            found = []
        }
        if uses.isEmpty { disconnectAll() }
        updateScan()
    }

    // MARK: Pairing (the Sensors screen, while it holds the manager)

    func scanForNew() {
        guard uses.contains(.sensorsScreen) else { return }
        isScanningForNew = true
        updateScan()
    }

    func stopScanningForNew() {
        isScanningForNew = false
        updateScan()
    }

    func pair(_ id: UUID) {
        guard let sensor = found.first(where: { $0.id == id }) else { return }
        store.remember(PairedSensor(id: sensor.id, name: sensor.name, kinds: sensor.kinds))
        paired = store.all
        found.removeAll { $0.id == id }
        connectPaired()
    }

    func forget(_ id: UUID) {
        store.forget(id)
        paired = store.all
        if let p = peripherals.removeValue(forKey: id) { central?.cancelPeripheralConnection(p) }
        connections[id] = nil
        batteries[id] = nil
        hub.disconnected(id)
        updateScan()
    }

    // MARK: Connecting

    private func startBluetooth() {
        guard central == nil else { return }
        central = CBCentralManager(delegate: link, queue: nil, options: [
            CBCentralManagerOptionRestoreIdentifierKey: Self.restoreIdentifier,
            CBCentralManagerOptionShowPowerAlertKey: false,           // the Sensors screen says when Bluetooth is off
        ])
    }

    private func isPaired(_ id: UUID) -> Bool { paired.contains { $0.id == id } }

    /// The paired sensors CoreBluetooth already knows, by identifier, and any another app has connected; a scan for the rest.
    private func connectPaired() {
        guard !uses.isEmpty, let central, central.state == .poweredOn else { return }
        let ids = paired.map(\.id)
        let known = central.retrievePeripherals(withIdentifiers: ids)
            + central.retrieveConnectedPeripherals(withServices: Self.scannedServices).filter { ids.contains($0.identifier) }
        for p in known { connect(p) }
        updateScan()
    }

    private func connect(_ p: CBPeripheral) {
        let id = p.identifier
        peripherals[id] = p
        p.delegate = link
        guard connections[id] == nil, let central else { return }
        connections[id] = .connecting
        // A pending connection never times out: it completes whenever the sensor is next in range, in the background too.
        central.connect(p)
    }

    private func disconnectAll() {
        for (id, p) in peripherals {
            central?.cancelPeripheralConnection(p)
            hub.disconnected(id)
        }
        connections = [:]
    }

    /// Scans while the Sensors screen is looking for new sensors, or while a paired one hasn't been found by identifier (iOS can
    /// forget a peripheral it hasn't seen for a while). Only for the four services: that's also what lets it scan in the background.
    private func updateScan() {
        guard let central, central.state == .poweredOn else {
            scanning = nil
            return
        }
        let missing = !uses.isEmpty && paired.contains { peripherals[$0.id] == nil }
        let wanted: Bool? = isScanningForNew ? true : missing ? false : nil
        guard wanted != scanning else { return }
        if scanning != nil { central.stopScan() }
        if let wanted {
            central.scanForPeripherals(withServices: Self.scannedServices,
                                       options: [CBCentralManagerScanOptionAllowDuplicatesKey: wanted])
        }
        scanning = wanted
    }

    // MARK: From the delegate

    fileprivate func stateChanged(_ state: CBManagerState) {
        bluetoothState = state
        if state == .poweredOn {
            // Connections restored after a relaunch that nothing has asked for since are dropped.
            if uses.isEmpty { disconnectAll() } else { connectPaired() }
        } else {
            // Off, reset or not allowed: every connection is gone, and the peripheral objects with them.
            for id in peripherals.keys { hub.disconnected(id) }
            peripherals = [:]
            connections = [:]
            scanning = nil
        }
        updateScan()
    }

    fileprivate func restored(_ restored: [CBPeripheral]) {
        for p in restored where isPaired(p.identifier) {
            peripherals[p.identifier] = p
            p.delegate = link
        }
    }

    fileprivate func discovered(_ p: CBPeripheral, advertisement: [String: Any], rssi: Int) {
        let id = p.identifier
        if isPaired(id) {
            if !uses.isEmpty {
                connect(p)
                updateScan()
            }
            return
        }
        guard isScanningForNew else { return }
        let services = (advertisement[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID] ?? []).compactMap(\.number)
        let name = advertisement[CBAdvertisementDataLocalNameKey] as? String ?? p.name ?? "Sensor"
        let previous = found.first { $0.id == id }
        let signal = rssi == 127 ? (previous?.signal ?? -100) : rssi           // 127: not available
        let sensor = Found(id: id, name: name, kinds: SensorKind.kinds(of: services), signal: signal)
        if let i = found.firstIndex(where: { $0.id == id }) { found[i] = sensor } else { found.append(sensor) }
    }

    fileprivate func didConnect(_ p: CBPeripheral) {
        guard isPaired(p.identifier), !uses.isEmpty else {           // forgotten or released while connecting
            central?.cancelPeripheralConnection(p)
            return
        }
        connections[p.identifier] = .connected
        p.discoverServices(Self.scannedServices + [CBUUID(string: GATT.uuidString(GATT.batteryService))])
    }

    /// Dropped (out of range, a flat battery) or failed to connect: asked for again at once while anything holds the manager.
    fileprivate func didDisconnect(_ p: CBPeripheral) {
        let id = p.identifier
        hub.disconnected(id)
        connections[id] = nil
        guard !uses.isEmpty, isPaired(id), peripherals[id] != nil, central?.state == .poweredOn else { return }
        connect(p)
    }

    /// Subscribes to what `GATT.characteristics(toRead:onTrainer:)` says, and keeps the kinds of a paired sensor up to date with
    /// what it really offers (an advertisement may not list every service).
    fileprivate func discoveredServices(_ p: CBPeripheral) {
        let services = p.services ?? []
        let kinds = SensorKind.kinds(of: services.compactMap(\.uuid.number))
        if !kinds.isEmpty, let sensor = paired.first(where: { $0.id == p.identifier }), sensor.kinds != kinds {
            store.remember(PairedSensor(id: sensor.id, name: sensor.name, kinds: kinds))
            paired = store.all
        }
        for service in services {
            guard let number = service.uuid.number,
                  let wanted = GATT.characteristics(toRead: number, onTrainer: kinds.contains(.trainer)) else { continue }
            p.discoverCharacteristics(wanted.map { CBUUID(string: GATT.uuidString($0)) }, for: service)
        }
    }

    fileprivate func discoveredCharacteristics(_ p: CBPeripheral, of service: CBService) {
        for c in service.characteristics ?? [] {
            if c.uuid.number == GATT.batteryLevel { p.readValue(for: c) }
            if c.properties.contains(.notify) { p.setNotifyValue(true, for: c) }
        }
    }

    fileprivate func received(_ value: Data, characteristic: UInt16, from p: CBPeripheral) {
        let id = p.identifier
        let now = ProcessInfo.processInfo.systemUptime
        switch characteristic {
        case GATT.heartRateMeasurement:
            if let m = HeartRateMeasurement(value) { hub.add(m, from: id, at: now) }
        case GATT.cscMeasurement:
            if let m = CSCMeasurement(value) { hub.add(m, from: id, at: now) }
        case GATT.cyclingPowerMeasurement:
            if let m = CyclingPowerMeasurement(value) { hub.add(m, from: id, at: now) }
        case GATT.indoorBikeData:
            if let m = IndoorBikeData(value) { hub.add(m, from: id, at: now) }
        case GATT.batteryLevel:
            if let percent = BatteryLevel.percent(value) { batteries[id] = percent }
        default:
            break
        }
    }
}

extension CBUUID {
    /// The 16-bit assigned number, for a Bluetooth SIG service or characteristic; nil for a vendor's 128-bit UUID.
    var number: UInt16? {
        let bytes = [UInt8](data)
        guard bytes.count == 2 else { return nil }
        return UInt16(bytes[0]) << 8 | UInt16(bytes[1])            // big-endian, unlike the values sent
    }
}

/// The CoreBluetooth delegates. With `queue: nil` the central calls back on the main thread, as `LocationFeed`'s manager does.
@MainActor
private final class BluetoothLink: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    weak var owner: SensorManager?

    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        let state = central.state
        MainActor.assumeIsolated { owner?.stateChanged(state) }
    }

    nonisolated func centralManager(_ central: CBCentralManager, willRestoreState dict: [String: Any]) {
        let restored = dict[CBCentralManagerRestoredStatePeripheralsKey] as? [CBPeripheral] ?? []
        MainActor.assumeIsolated { owner?.restored(restored) }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                                    advertisementData: [String: Any], rssi RSSI: NSNumber) {
        let rssi = RSSI.intValue
        MainActor.assumeIsolated { owner?.discovered(peripheral, advertisement: advertisementData, rssi: rssi) }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        MainActor.assumeIsolated { owner?.didConnect(peripheral) }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        MainActor.assumeIsolated { owner?.didDisconnect(peripheral) }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        MainActor.assumeIsolated { owner?.didDisconnect(peripheral) }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard error == nil else { return }
        MainActor.assumeIsolated { owner?.discoveredServices(peripheral) }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard error == nil else { return }
        MainActor.assumeIsolated { owner?.discoveredCharacteristics(peripheral, of: service) }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard error == nil, let value = characteristic.value, let number = characteristic.uuid.number else { return }
        MainActor.assumeIsolated { owner?.received(value, characteristic: number, from: peripheral) }
    }
}
