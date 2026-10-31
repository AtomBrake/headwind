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
                } else {
                    Label("Timed: no GPS. Record it on your Watch for heart rate and calories.", systemImage: "timer")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(.regularMaterial, in: Capsule())
                }
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
            // A timed session: its time, and what the Watch measured.
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
                GridRow {
                    Stat(value: Units.duration(seconds: summary.movingTime), caption: "Time")
                    if summary.sport.hasDistance, summary.distance > 0 {
                        Stat(value: units.distance(metres: summary.distance, sport: summary.sport), caption: "Distance")
                    } else {
                        Stat(value: summary.averageHeartRate.map { "\($0) bpm" } ?? "–", caption: "Avg heart rate")
                    }
                }
                if let kcal = summary.calories {
                    GridRow {
                        Stat(value: Units.whole(kcal), caption: "Active calories")
                        Color.clear.frame(height: 1)
                    }
                }
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
            if let hr = summary.averageHeartRate {
                GridRow {
                    Stat(value: "\(hr) bpm", caption: "Avg heart rate")
                    if let power = summary.averagePower {
                        Stat(value: "\(power) W", caption: "Avg power")
                    } else {
                        Color.clear.frame(height: 1)
                    }
                }
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
