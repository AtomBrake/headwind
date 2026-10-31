import SwiftUI

/// Pair, forget and check the phone's Bluetooth sensors: each paired one with its connection, battery and live reading, and the ones nearby to
/// pair. Opening it is what asks for Bluetooth (the sensor manager makes its central only then), and it scans only while it's open.
struct SensorsView: View {
    @Environment(SensorManager.self) private var sensors
    @Environment(Session.self) private var session

    var body: some View {
        List {
            radioSection
            if !sensors.paired.isEmpty {
                Section("Paired") {
                    ForEach(sensors.paired) { sensor in
                        PairedSensorRow(sensor: sensor, units: session.units)
                            .swipeActions {
                                Button("Forget", role: .destructive) { sensors.forget(sensor.id) }
                            }
                            .contextMenu {
                                Button("Forget", systemImage: "trash", role: .destructive) { sensors.forget(sensor.id) }
                            }
                    }
                }
            }
            if sensors.radio == .on {
                nearbySection
            }
            wheelSection
            Section {
            } footer: {
                Text("Sensors are remembered on this iPhone only: on another phone, pair them again. They connect while the Record tab is open and while recording, and keep sending with the screen locked. Smart trainers need Bluetooth FTMS (Fitness Machine); older ones that don't have it may show only as a power meter.")
            }
        }
        .navigationTitle("Sensors")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { sensors.use(.sensorsScreen) }
        .onDisappear { sensors.stopUsing(.sensorsScreen) }
    }

    @ViewBuilder private var radioSection: some View {
        switch sensors.radio {
        case .off:
            Section {
                Label("Bluetooth is off. Turn it on in Control Centre to use your sensors.", systemImage: "antenna.radiowaves.left.and.right.slash")
            }
        case .denied:
            Section {
                Label("Headwind isn't allowed to use Bluetooth, so it can't reach your sensors.", systemImage: "hand.raised")
                if let settings = URL(string: UIApplication.openSettingsURLString) {
                    Link("Open Settings", destination: settings)
                }
            }
        case .unsupported:
            Section {
                Label("This device has no Bluetooth LE.", systemImage: "exclamationmark.triangle")
            }
        case .notAsked, .starting:
            Section {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Starting Bluetooth…").foregroundStyle(.secondary)
                }
            }
        case .on:
            EmptyView()
        }
    }

    private var nearbySection: some View {
        Section {
            if sensors.found.isEmpty {
                Text("Looking for heart rate straps, power meters, speed and cadence sensors and smart trainers…")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            ForEach(sensors.found.sorted { $0.rssi > $1.rssi }) { sensor in
                Button { sensors.pair(sensor) } label: {
                    HStack(spacing: 12) {
                        Image(systemName: sensor.kind.systemImage)
                            .foregroundStyle(Color.accentColor)
                            .frame(width: 28)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(sensor.name).foregroundStyle(.primary)
                            Text(sensor.kind.title).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "cellularbars", variableValue: Self.signal(sensor.rssi))
                            .foregroundStyle(.secondary)
                            .accessibilityLabel("Signal \(Int(Self.signal(sensor.rssi) * 3)) of 3")
                        Text("Pair").font(.callout.weight(.semibold))
                    }
                }
                .accessibilityIdentifier("pair-sensor")
            }
        } header: {
            HStack(spacing: 6) {
                Text("Nearby")
                if sensors.isScanning { ProgressView().controlSize(.mini) }
            }
        } footer: {
            Text("Wake a sensor to find it: put the strap on, turn the cranks, or spin the wheel. A sensor paired with another app or a head unit may need letting go of there first.")
        }
    }

    private var wheelSection: some View {
        Section {
            Picker("Tyre", selection: Binding(get: { sensors.wheelMillimetres }, set: { sensors.setWheel(millimetres: $0) })) {
                if !WheelSize.common.contains(where: { $0.mm == sensors.wheelMillimetres }) {
                    Text("Your own").tag(sensors.wheelMillimetres)
                }
                ForEach(WheelSize.common, id: \.mm) { size in
                    Text("\(size.name) (\(size.mm) mm)").tag(size.mm)
                }
            }
            LabeledContent("Circumference") {
                // One HStack: LabeledContent stacks several views one above the other.
                HStack(spacing: 4) {
                    TextField("mm", value: Binding(get: { sensors.wheelMillimetres }, set: { sensors.setWheel(millimetres: $0) }),
                              format: .number.grouping(.never))
                        .keyboardType(.numberPad)
                        .multilineTextAlignment(.trailing)
                        .frame(maxWidth: 90)
                    Text("mm").foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Wheel")
        } footer: {
            Text("A wheel sensor's speed and distance on an indoor ride come from this. Outdoors, GPS gives the ride's distance. \(WheelSize.defaultMillimetres) mm unless you change it.")
        }
    }

    /// RSSI in dBm as 0…1 for the signal bars.
    static func signal(_ rssi: Int) -> Double {
        switch rssi {
        case (-60)...: 1
        case -75 ..< -60: 2.0 / 3
        case -90 ..< -75: 1.0 / 3
        default: 0
        }
    }
}

/// A paired sensor: its kind, whether it's connected, its battery, and what it's reading now.
private struct PairedSensorRow: View {
    var sensor: SensorManager.Paired
    var units: Units
    @Environment(SensorManager.self) private var sensors

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: sensor.kind.systemImage)
                .foregroundStyle(link == .connected ? Color.accentColor : .secondary)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(sensor.name)
                Text("\(sensor.kind.title) · \(status)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if link == .connected {
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        Text(reading(at: context.date))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.primary)
                    }
                }
            }
            Spacer()
            if let level = sensors.battery[sensor.id] {
                Label("\(level)%", systemImage: Self.batteryImage(level))
                    .font(.caption)
                    .foregroundStyle(level <= 15 ? .orange : .secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var link: SensorManager.Link { sensors.links[sensor.id] ?? .idle }

    private var status: String {
        switch link {
        case .connected: "Connected"
        case .connecting: "Looking for it…"
        case .idle: sensors.radio == .on ? "Not connected" : "Bluetooth unavailable"
        }
    }

    private func reading(at date: Date) -> String {
        guard let r = sensors.readings(of: sensor.id, at: date), !r.isEmpty else { return "No reading yet" }
        var parts: [String] = []
        if let hr = r.heartRate { parts.append("\(hr) bpm") }
        if let power = r.power { parts.append("\(power) W") }
        if let cadence = r.cadence { parts.append("\(cadence) rpm") }
        if let speed = r.speed { parts.append(units.speed(metresPerSecond: speed)) }
        return parts.isEmpty ? "No reading yet" : parts.joined(separator: " · ")
    }

    private static func batteryImage(_ level: Int) -> String {
        switch level {
        case 88...: "battery.100percent"
        case 63..<88: "battery.75percent"
        case 38..<63: "battery.50percent"
        case 13..<38: "battery.25percent"
        default: "battery.0percent"
        }
    }
}
