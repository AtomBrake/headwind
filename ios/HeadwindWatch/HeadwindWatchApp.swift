import SwiftUI

@main
struct HeadwindWatchApp: App {
    /// The shared one, so the Action button's intents and these screens drive the same workout.
    @State private var workout = WorkoutManager.shared

    var body: some Scene {
        WindowGroup {
            WatchRootView()
                .environment(workout)
                .environment(workout.phone)
        }
    }
}

struct WatchRootView: View {
    @Environment(WorkoutManager.self) private var workout

    var body: some View {
        switch workout.state {
        case .idle, .starting:
            NavigationStack { StartView() }   // for the sport and bike pickers
        case .recording, .paused:
            RecordingView()
        case .saving:
            ProgressView("Saving \(workout.sport.title.lowercased())…")
        case .finished:
            SummaryView()
        }
    }
}

struct StartView: View {
    @Environment(WorkoutManager.self) private var workout
    @Environment(PhoneLink.self) private var phone

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                if let recovered = workout.recovered {
                    VStack(spacing: 6) {
                        Text("Unfinished \(recovered.sport.title.lowercased()) from \(recovered.start.formatted(date: .omitted, time: .shortened))")
                            .font(.footnote)
                            .multilineTextAlignment(.center)
                        HStack {
                            Button("Save") { workout.saveRecovered() }
                            Button("Discard", role: .destructive) { workout.discardRecovered() }
                        }
                    }
                    .padding(.bottom, 4)
                }

                Button {
                    Task { await workout.start(bike: Bike.pick(workout.chosenBike, from: phone.bikes)) }
                } label: {
                    VStack(spacing: 4) {
                        Image(systemName: workout.sport.systemImage)
                            .font(.system(size: 36, weight: .semibold))
                        Text("Start \(workout.sport.title.lowercased())").font(.headline)
                    }
                    .frame(maxWidth: .infinity, minHeight: 100)
                }
                .tint(.accentColor)
                .disabled(workout.state == .starting)
                .accessibilityIdentifier("watch-start-ride")

                Picker("Sport", selection: Binding(get: { workout.sport }, set: { workout.choose(sport: $0) })) {
                    ForEach(Sport.allCases) { sport in
                        Label(sport.title, systemImage: sport.systemImage).tag(sport)
                    }
                }
                .pickerStyle(.navigationLink)
                .disabled(workout.state == .starting)
                .accessibilityIdentifier("watch-sport-picker")

                if workout.sport == .poolSwim {
                    Picker("Pool", selection: Binding(get: { workout.poolLength }, set: { workout.choose(poolLength: $0) })) {
                        ForEach([25.0, 33.33, 50.0, 22.86], id: \.self) { length in
                            Text(length == 22.86 ? "25 yd" : "\(length.formatted(.number.precision(.fractionLength(0)))) m").tag(length)
                        }
                    }
                    .pickerStyle(.navigationLink)
                    .disabled(workout.state == .starting)
                }

                if workout.sport.isRide, !phone.bikes.isEmpty {
                    Picker("Bike", selection: Binding(get: { Bike.pick(workout.chosenBike, from: phone.bikes) },
                                                      set: { workout.choose(bike: $0) })) {
                        if Bike.pick(workout.chosenBike, from: phone.bikes) == nil {
                            Text("No bike").tag(Int?.none)
                        }
                        ForEach(phone.bikes) { bike in
                            Text(bike.name).tag(Int?.some(bike.id))
                        }
                    }
                    .pickerStyle(.navigationLink)
                    .disabled(workout.state == .starting)
                }

                if !phone.phonePaired {
                    Text("Pair the Headwind iPhone app with your server so rides can upload.")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                        .multilineTextAlignment(.center)
                }
                if let error = workout.error {
                    Text(error.localizedDescription).font(.footnote).foregroundStyle(.red).multilineTextAlignment(.center)
                }
            }
        }
        .navigationTitle("Headwind")
    }
}

struct RecordingView: View {
    @Environment(WorkoutManager.self) private var workout
    @State private var page = 1

    var body: some View {
        TabView(selection: $page) {
            ControlsPage().tag(0)
            MetricsPage().tag(1)
        }
        .tabViewStyle(.page)
    }
}

private struct MetricsPage: View {
    @Environment(WorkoutManager.self) private var workout
    @Environment(PhoneLink.self) private var phone

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let sport = workout.sport
            let elapsed = workout.clock.elapsed(at: context.date)
            VStack(alignment: .leading, spacing: 2) {
                Text(Units.clock(seconds: elapsed))
                    .font(.system(size: 34, weight: .semibold, design: .rounded))
                    .foregroundStyle(workout.state == .paused ? .yellow : .accentColor)
                    .monospacedDigit()
                if sport.usesGPS {
                    metric(phone.units.distance(metres: workout.tracker.distance, sport: sport))
                    metric(phone.units.rate(metresPerSecond: workout.tracker.currentSpeed, sport: sport))
                } else if sport.hasDistance, workout.healthDistance > 0 {
                    // Lengths swum, a treadmill's steps, a speed sensor: HealthKit's distance, and the average rate over the session.
                    metric(phone.units.distance(metres: workout.healthDistance, sport: sport))
                    metric(phone.units.rate(metresPerSecond: elapsed > 0 ? workout.healthDistance / elapsed : 0, sport: sport))
                }
                HStack(spacing: 4) {
                    metric(workout.heartRate.map { "\($0)" } ?? "--")
                    Image(systemName: "heart.fill").foregroundStyle(.red).font(.footnote)
                }
                if let power = workout.power {
                    metric("\(power) W" + (workout.cadence.map { " · \($0) rpm" } ?? ""))
                } else if let cadence = workout.cadence {
                    metric("\(cadence) rpm")
                }
                if sport.usesGPS && !sport.isSwim {
                    metric(phone.units.elevation(metres: workout.tracker.elevationGain) + " ↑")
                } else {
                    metric("\(Units.whole(workout.activeEnergy)) kcal")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scenePadding()
    }

    private func metric(_ text: String) -> some View {
        Text(text)
            .font(.system(.title3, design: .rounded).monospacedDigit())
            .lineLimit(1)
            .minimumScaleFactor(0.7)
    }
}

private struct ControlsPage: View {
    @Environment(WorkoutManager.self) private var workout

    var body: some View {
        HStack(spacing: 12) {
            VStack {
                Button { workout.end() } label: {
                    Image(systemName: "xmark")
                }
                .tint(.red)
                .font(.title2)
                .accessibilityIdentifier("watch-end-ride")
                Text("End")
            }
            VStack {
                Button {
                    workout.state == .paused ? workout.resume() : workout.pause()
                } label: {
                    Image(systemName: workout.state == .paused ? "play" : "pause")
                }
                .tint(.yellow)
                .font(.title2)
                Text(workout.state == .paused ? "Resume" : "Pause")
            }
        }
    }
}

struct SummaryView: View {
    @Environment(WorkoutManager.self) private var workout
    @Environment(PhoneLink.self) private var phone

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                if let s = workout.lastSummary {
                    Text(GPXWriter.rideName(s)).font(.headline)
                    if s.sport.hasDistance, s.distance > 0 {
                        LabeledContent("Distance", value: phone.units.distance(metres: s.distance, sport: s.sport))
                    }
                    LabeledContent(s.sport.usesGPS ? "Moving" : "Time", value: Units.duration(seconds: s.movingTime))
                    if s.sport.usesGPS && !s.sport.isSwim {
                        LabeledContent("Climbing", value: phone.units.elevation(metres: s.elevationGain))
                    }
                    if let hr = s.averageHeartRate {
                        LabeledContent("Avg HR", value: "\(hr) bpm")
                    }
                    if let power = s.averagePower {
                        LabeledContent("Avg power", value: "\(power) W")
                    }
                    if let kcal = s.calories {
                        LabeledContent("Active", value: "\(Units.whole(kcal)) kcal")
                    }
                }
                // Nothing to report when nothing was sent: too short to keep, or the Watch couldn't store it (the error says which).
                if !workout.lastSent {
                    EmptyView()
                } else if phone.waitingToSend == 0, let direct = phone.lastDirect, -direct.timeIntervalSinceNow < 3600 {
                    Label("Uploaded to Headwind", systemImage: "checkmark.icloud")
                        .font(.footnote)
                        .foregroundStyle(.green)
                } else if phone.waitingToSend > 0, let problem = phone.sendProblem {
                    Label("Not sent to iPhone: \(problem)", systemImage: "exclamationmark.circle")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                } else {
                    Label(phone.waitingToSend > 0 ? "Sending to iPhone…" : "Sent to iPhone",
                          systemImage: phone.waitingToSend > 0 ? "arrow.up.circle" : "checkmark.circle")
                        .font(.footnote)
                        .foregroundStyle(phone.waitingToSend > 0 ? Color.secondary : Color.green)
                }
                if let error = workout.error {
                    Text(error.localizedDescription).font(.footnote).foregroundStyle(.orange)
                }
                Button("Done") { workout.dismissSummary() }
                    .padding(.top, 4)
            }
        }
    }
}
