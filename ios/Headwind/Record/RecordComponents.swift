import SwiftUI

/// The sport and bike pickers and Start, or pause / resume / finish, depending on the recorder's state.
struct RecordControls: View {
    var recorder: PhoneRideRecorder
    var bikes: [Bike]
    var onStart: () -> Void
    var onFinish: () -> Void

    var body: some View {
        switch recorder.state {
        case .idle:
            IdleControls(recorder: recorder, bikes: bikes, onStart: onStart)
        case .recording, .paused:
            HStack(spacing: 12) {
                if recorder.state == .recording {
                    Button(action: recorder.pause) {
                        Label("Pause", systemImage: "pause.fill").frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.bordered)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                } else {
                    Button(action: recorder.resume) {
                        Label("Resume", systemImage: "play.fill").frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .buttonStyle(.borderedProminent)
                }
                Button(action: onFinish) {
                    Label("Finish", systemImage: "stop.fill").frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
                .accessibilityIdentifier("finish-ride")
            }
            .controlSize(.large)
        }
    }
}

private struct IdleControls: View {
    var recorder: PhoneRideRecorder
    var bikes: [Bike]
    var onStart: () -> Void
    @Environment(Router.self) private var router

    var body: some View {
        VStack(spacing: 8) {
            if recorder.sport.usesGPS && (recorder.authorization == .denied || recorder.authorization == .restricted) {
                SportAndBikePicker(recorder: recorder, bikes: bikes)   // a timed sport needs no location, so let one be picked
                Label("Location access is off. Allow it in Settings to record rides.", systemImage: "location.slash")
                    .font(.callout)
                    .padding(12)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                if let settings = URL(string: UIApplication.openSettingsURLString) {
                    Link("Open Settings", destination: settings)
                }
            } else {
                SportAndBikePicker(recorder: recorder, bikes: bikes)
                Button(action: onStart) {
                    Label("Start \(recorder.sport.title.lowercased())", systemImage: recorder.sport.systemImage)
                        .font(.title3.bold())
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .accessibilityIdentifier("start-ride")
                if recorder.sport.usesGPS {
                    Label(recorder.gpsReady ? "GPS ready" : "Waiting for GPS…",
                          systemImage: recorder.gpsReady ? "location.fill" : "location")
                        .font(.caption)
                        .foregroundStyle(recorder.gpsReady ? .green : .secondary)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(.regularMaterial, in: Capsule())
                } else if recorder.hasSensors {
                    Label("Timed: no GPS. \(recorder.sport.isRide ? "Heart rate, power, cadence and distance" : "Heart rate") from your sensors.",
                          systemImage: "timer")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(.regularMaterial, in: Capsule())
                } else {
                    Label("Timed: no GPS. Record it on your Watch, or pair sensors, for heart rate.", systemImage: "timer")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(.regularMaterial, in: Capsule())
                }
                SensorsChip { router.show(.sensors) }
            }
        }
    }
}

/// Shown before Start only: once recording, the sport and bike are fixed.
private struct SportAndBikePicker: View {
    var recorder: PhoneRideRecorder
    var bikes: [Bike]

    var body: some View {
        HStack(spacing: 8) {
            Picker("Sport", selection: Binding(get: { recorder.sport }, set: { recorder.choose(sport: $0) })) {
                ForEach(Sport.phoneSports) { sport in
                    Label(sport.title, systemImage: sport.systemImage).tag(sport)
                }
            }
            .accessibilityIdentifier("sport-picker")
            if recorder.sport.isRide, !bikes.isEmpty {
                Picker("Bike", selection: Binding(get: { Bike.pick(recorder.chosenBike, from: bikes) }, set: { recorder.choose(bike: $0) })) {
                    // Nothing is picked only when the rider has no default bike, and the server then leaves the ride without one.
                    if Bike.pick(recorder.chosenBike, from: bikes) == nil {
                        Text("No bike").tag(Int?.none)
                    }
                    ForEach(bikes) { bike in
                        Text(bike.name).tag(Int?.some(bike.id))
                    }
                }
                .accessibilityIdentifier("bike-picker")
            }
        }
        .pickerStyle(.menu)
        .padding(.horizontal, 6)
        .background(.regularMaterial, in: Capsule())
    }
}

struct RideStatsPanel: View {
    var recorder: PhoneRideRecorder
    var units: Units

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(spacing: 10) {
                Text(Units.clock(seconds: recorder.clock.elapsed(at: context.date)))
                    .font(.system(size: recorder.sport.usesGPS ? 44 : 72, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .accessibilityIdentifier("ride-elapsed")
                let live = recorder.liveSensors(at: context.date)
                if recorder.sport.usesGPS {
                    Grid(horizontalSpacing: 12, verticalSpacing: 10) {
                        GridRow {
                            Stat(value: units.distance(metres: recorder.tracker.distance), caption: "Distance")
                            Stat(value: units.rate(metresPerSecond: recorder.tracker.currentSpeed, sport: recorder.sport),
                                 caption: Units.rateCaption(recorder.sport))
                        }
                        GridRow {
                            Stat(value: units.rate(metresPerSecond: recorder.tracker.averageSpeed, sport: recorder.sport),
                                 caption: Units.rateCaption(recorder.sport, average: true))
                            Stat(value: units.elevation(metres: recorder.tracker.elevationGain), caption: "Climbing")
                        }
                    }
                    if let live {
                        SensorStatsRow(readings: live, isRide: recorder.sport.isRide)
                    }
                } else if let live {
                    // A timed session with sensors: what they say, and an indoor ride's distance by sensor.
                    SensorStatsRow(readings: live, isRide: recorder.sport.isRide)
                    if recorder.sport.isRide {
                        Grid(horizontalSpacing: 12, verticalSpacing: 10) {
                            GridRow {
                                Stat(value: live.speed.map { units.speed(metresPerSecond: $0) } ?? "–", caption: "Speed")
                                Stat(value: units.distance(metres: recorder.session.distance), caption: "Distance")
                            }
                        }
                    }
                    if recorder.state == .paused {
                        Text("Paused").font(.headline).foregroundStyle(.secondary)
                    }
                } else {
                    // A timer: nothing else to show from the phone alone.
                    Text(recorder.state == .paused ? "Paused" : recorder.sport.title)
                        .font(.headline)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
    }
}

/// Live heart rate, 3 s power and cadence from the phone's sensors; a dash for one that has nothing to say (out of range, not paired).
struct SensorStatsRow: View {
    var readings: SensorReadings
    var isRide: Bool

    var body: some View {
        Grid(horizontalSpacing: 12, verticalSpacing: 10) {
            GridRow {
                Stat(value: readings.heartRate.map { "\($0) bpm" } ?? "–", caption: "Heart rate")
                if isRide {
                    Stat(value: readings.power.map { "\($0) W" } ?? "–", caption: "Power (3 s)")
                    Stat(value: readings.cadence.map { "\($0) rpm" } ?? "–", caption: "Cadence")
                }
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// Before Start, with sensors paired: how many are connected, opening the Sensors screen.
struct SensorsChip: View {
    @Environment(SensorManager.self) private var sensors
    var open: () -> Void

    var body: some View {
        if sensors.hasPaired {
            Button(action: open) {
                Label(label, systemImage: sensors.connectedCount > 0 ? "sensor.fill" : "sensor")
                    .font(.caption)
                    .foregroundStyle(sensors.connectedCount > 0 ? .green : .secondary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(.regularMaterial, in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("sensors-chip")
        }
    }

    private var label: String {
        let n = sensors.paired.count, on = sensors.connectedCount
        if sensors.radio == .off { return "Bluetooth is off" }
        if on == n { return n == 1 ? "\(sensors.paired[0].name) connected" : "\(n) sensors connected" }
        return on == 0 ? "Looking for your sensors…" : "\(on) of \(n) sensors connected"
    }
}

struct RecoveredBanner: View {
    var start: Date
    var sport: Sport
    var save: () -> Void
    var discard: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Unfinished \(sport.title.lowercased()) from \(start.formatted(date: .abbreviated, time: .shortened))",
                  systemImage: "exclamationmark.arrow.circlepath")
                .font(.callout.weight(.semibold))
            Text("Headwind stopped before this ride was saved. Save what was recorded?")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack {
                Button("Save", action: save).buttonStyle(.borderedProminent)
                Button("Discard", role: .destructive, action: discard).buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

struct RideSavedSheet: View {
    var rideID: SavedRide.ID
    @Environment(Session.self) private var session
    @Environment(RideStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            if let ride = store.rides.first(where: { $0.id == rideID }) {
                VStack(spacing: 20) {
                    RideSummaryGrid(summary: ride.summary, units: session.units)
                    UploadStatusLabel(ride: ride)
                    if ride.status == .failed {
                        Button("Try again") { Task { await store.uploadPending(using: session) } }
                    }
                    Spacer()
                }
                .padding(20)
                .navigationTitle(ride.name)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            }
        }
    }
}

struct RideSummaryGrid: View {
    var summary: RideSummary
    var units: Units

    var body: some View {
        if !summary.sport.usesGPS {
            // A timed session: its time, and what the Watch or the phone's sensors measured.
            let distance = summary.sport.hasDistance && summary.distance > 0
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
                GridRow {
                    Stat(value: Units.duration(seconds: summary.movingTime), caption: "Time")
                    if distance {
                        Stat(value: units.distance(metres: summary.distance, sport: summary.sport), caption: "Distance")
                    } else {
                        Stat(value: summary.averageHeartRate.map { "\($0) bpm" } ?? "–", caption: "Avg heart rate")
                    }
                }
                statRows((distance ? heartRate : []) + sensorStats + (summary.calories.map { [(Units.whole($0), "Active calories")] } ?? []))
            }
        } else {
            trackGrid
        }
    }

    private var trackGrid: some View {
        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
            GridRow {
                Stat(value: units.distance(metres: summary.distance, sport: summary.sport), caption: "Distance")
                Stat(value: Units.duration(seconds: summary.movingTime), caption: "Moving time")
            }
            GridRow {
                Stat(value: units.rate(metresPerSecond: summary.movingTime > 0 ? summary.distance / summary.movingTime : 0, sport: summary.sport),
                     caption: Units.rateCaption(summary.sport, average: true))
                Stat(value: units.elevation(metres: summary.elevationGain), caption: "Climbing")
            }
            statRows(heartRate + sensorStats)
        }
    }

    private var heartRate: [(String, String)] {
        summary.averageHeartRate.map { [("\($0) bpm", "Avg heart rate")] } ?? []
    }

    private var sensorStats: [(String, String)] {
        var stats: [(String, String)] = []
        if let power = summary.averagePower { stats.append(("\(power) W", "Avg power")) }
        if let cadence = summary.averageCadence { stats.append(("\(cadence) rpm", "Avg cadence")) }
        return stats
    }
}

/// Stats (value, caption) two to a row, for a Grid of two columns.
private func statRows(_ stats: [(String, String)]) -> some View {
    ForEach(Array(stride(from: 0, to: stats.count, by: 2)), id: \.self) { i in
        GridRow {
            Stat(value: stats[i].0, caption: stats[i].1)
            if i + 1 < stats.count {
                Stat(value: stats[i + 1].0, caption: stats[i + 1].1)
            } else {
                Color.clear.frame(height: 1)
            }
        }
    }
}

struct UploadStatusLabel: View {
    var ride: SavedRide

    var body: some View {
        switch ride.status {
        case .pending:
            Label("Waiting to upload", systemImage: "clock").foregroundStyle(.secondary)
        case .uploading:
            HStack(spacing: 6) { ProgressView(); Text("Uploading to Headwind…") }.foregroundStyle(.secondary)
        case .uploaded:
            Label(ride.message ?? "Uploaded to Headwind", systemImage: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .failed:
            Label(ride.message ?? "Upload failed", systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
        case .rejected:
            Label("Headwind refused this recording: \(ride.message ?? "it couldn't be read").", systemImage: "xmark.octagon.fill")
                .foregroundStyle(.red)
        }
    }
}
