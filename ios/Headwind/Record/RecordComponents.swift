import SwiftUI

/// Start, or pause / resume / finish, depending on the recorder's state.
struct RecordControls: View {
    var recorder: PhoneRideRecorder
    var onStart: () -> Void
    var onFinish: () -> Void

    var body: some View {
        switch recorder.state {
        case .idle:
            IdleControls(recorder: recorder, onStart: onStart)
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
    var onStart: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            if recorder.authorization == .denied || recorder.authorization == .restricted {
                Label("Location access is off. Allow it in Settings to record rides.", systemImage: "location.slash")
                    .font(.callout)
                    .padding(12)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                if let settings = URL(string: UIApplication.openSettingsURLString) {
                    Link("Open Settings", destination: settings)
                }
            } else {
                Button(action: onStart) {
                    Label("Start ride", systemImage: "bicycle")
                        .font(.title3.bold())
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .accessibilityIdentifier("start-ride")
                Label(recorder.gpsReady ? "GPS ready" : "Waiting for GPS…",
                      systemImage: recorder.gpsReady ? "location.fill" : "location")
                    .font(.caption)
                    .foregroundStyle(recorder.gpsReady ? .green : .secondary)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(.regularMaterial, in: Capsule())
            }
        }
    }
}

struct RideStatsPanel: View {
    var recorder: PhoneRideRecorder
    var units: Units

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            VStack(spacing: 10) {
                Text(Units.clock(seconds: recorder.clock.elapsed(at: context.date)))
                    .font(.system(size: 44, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .accessibilityIdentifier("ride-elapsed")
                Grid(horizontalSpacing: 12, verticalSpacing: 10) {
                    GridRow {
                        Stat(value: units.distance(metres: recorder.tracker.distance), caption: "Distance")
                        Stat(value: units.speed(metresPerSecond: recorder.tracker.currentSpeed), caption: "Speed")
                    }
                    GridRow {
                        Stat(value: units.speed(metresPerSecond: recorder.tracker.averageSpeed), caption: "Avg speed")
                        Stat(value: units.elevation(metres: recorder.tracker.elevationGain), caption: "Climbing")
                    }
                }
            }
            .padding(16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        }
    }
}

struct RecoveredBanner: View {
    var start: Date
    var save: () -> Void
    var discard: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Unfinished ride from \(start.formatted(date: .abbreviated, time: .shortened))", systemImage: "exclamationmark.arrow.circlepath")
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
                .navigationTitle(GPXWriter.rideName(start: ride.summary.start))
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
        Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
            GridRow {
                Stat(value: units.distance(metres: summary.distance), caption: "Distance")
                Stat(value: Units.duration(seconds: summary.movingTime), caption: "Moving time")
            }
            GridRow {
                Stat(value: units.speed(metresPerSecond: summary.movingTime > 0 ? summary.distance / summary.movingTime : 0), caption: "Avg speed")
                Stat(value: units.elevation(metres: summary.elevationGain), caption: "Climbing")
            }
            if let hr = summary.averageHeartRate {
                GridRow {
                    Stat(value: "\(hr) bpm", caption: "Avg heart rate")
                    Color.clear.frame(height: 1)
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
        }
    }
}
