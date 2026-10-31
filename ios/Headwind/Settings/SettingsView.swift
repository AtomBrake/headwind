import SwiftUI

struct SettingsView: View {
    @Environment(Session.self) private var session
    @Environment(HealthSync.self) private var health
    @Environment(SensorManager.self) private var sensors
    @State private var confirmUnpair = false
    @State private var confirmRemoveHealth = false
    @State private var healthError: AppError?

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    LabeledContent("Address", value: session.pairing?.server.absoluteString ?? "–")
                    LabeledContent("Rider", value: session.info?.rider ?? "–")
                    LabeledContent("Units", value: session.units.metric ? "Metric" : "Imperial")
                    if let server = session.pairing?.server {
                        Link("Open Headwind in Safari", destination: server)
                    }
                }

                Section {
                    NavigationLink {
                        SensorsView()
                    } label: {
                        LabeledContent("Bluetooth sensors", value: sensorsSummary)
                    }
                    .accessibilityIdentifier("settings-sensors")
                } header: {
                    Text("Sensors")
                } footer: {
                    Text("Heart rate straps, power meters, speed and cadence sensors and smart trainers, for recording on the phone without the Watch.")
                }

                if HealthSync.isAvailable {
                    healthSection
                }

                Section {
                    Button("Unpair this phone", role: .destructive) { confirmUnpair = true }
                } footer: {
                    Text("Unpairing forgets the token on this phone, and your Apple Watch's. To stop the tokens working entirely, revoke them on your server's Phones page too.")
                }

                Section {
                    LabeledContent("App version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "–")
                    LabeledContent("Server API", value: session.info?.api.map(String.init) ?? "–")
                }
            }
            .navigationTitle("Settings")
            .confirmationDialog("Unpair this phone?", isPresented: $confirmUnpair, titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { session.unpair() }
            }
            .confirmationDialog("Remove Apple Health data from Headwind?", isPresented: $confirmRemoveHealth, titleVisibility: .visible) {
                Button("Remove and stop sending", role: .destructive) {
                    Task {
                        do throws(AppError) { try await health.removeAll(using: session) } catch { healthError = error }
                    }
                }
            } message: {
                Text("Steps, sleep, heart rate, weigh-ins and calories sent from Apple Health are deleted from the server. Workouts already uploaded stay; delete those from Activities. Nothing in Apple Health changes.")
            }
            .alert("Apple Health", isPresented: Binding(get: { healthError != nil }, set: { if !$0 { healthError = nil } }),
                   presenting: healthError) { _ in
                Button("OK", role: .cancel) {}
            } message: { e in
                Text(e.localizedDescription)
            }
        }
    }

    private var sensorsSummary: String {
        switch sensors.paired.count {
        case 0: "None"
        case 1: sensors.paired[0].name
        case let n: "\(n) paired"
        }
    }

    private var healthSection: some View {
        Section {
            ForEach(HealthMetric.allCases) { metric in
                Toggle(isOn: Binding(get: { health.enabled.contains(metric) },
                                     set: { on in Task { await health.set(metric, on: on, using: session) } })) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(metric.title)
                        Text(metric.detail).font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Picker("Send history from", selection: Binding(get: { health.backfillDays }, set: { health.backfillDays = $0 })) {
                ForEach(HealthSync.backfillChoices, id: \.self) { days in
                    Text(days >= 365 ? "The last \(days / 365) year\(days >= 730 ? "s" : "")" : "The last \(days) days").tag(days)
                }
            }
            if !health.enabled.isEmpty {
                Button {
                    Task { await health.sync(using: session) }
                } label: {
                    HStack {
                        Text("Send now")
                        Spacer()
                        if health.syncing { ProgressView() }
                    }
                }
                .disabled(health.syncing)
                if let last = health.lastSync {
                    LabeledContent("Last sent", value: last.formatted(.relative(presentation: .named)))
                }
                if health.enabled.contains(.workouts), health.workoutsSent > 0 || health.workoutsSkipped > 0 {
                    LabeledContent("Workouts sent", value: "\(health.workoutsSent)" + (health.workoutsSkipped > 0 ? " · \(health.workoutsSkipped) of a sport Headwind doesn't have" : ""))
                }
                if let error = health.lastError {
                    Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
                }
            }
            Button("Remove Apple Health data from Headwind", role: .destructive) { confirmRemoveHealth = true }
        } header: {
            Text("Apple Health")
        } footer: {
            Text("Headwind reads only what's switched on, and sends it to your own server. For riders without a Garmin, or days without one: Garmin's figure wins on a day it has one. Change what Headwind may read in the Health app, under Sharing → Apps.")
        }
    }
}
