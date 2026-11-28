import ActivityKit
import Foundation
import Observation

/// The recording's Live Activity (RecordingActivityAttributes, drawn by the HeadwindWidgets extension): started when a recording starts,
/// kept up to date every `every` seconds and at once when it pauses, resumes or starts or stops sharing its live link, and ended when the
/// recording is finished or discarded. The clock counts up on the Lock Screen by itself (`timerStart`), so the updates are only for the
/// distance, the speed or pace, heart rate and the link. Nothing happens when Live Activities are switched off for Headwind in Settings.
@MainActor
final class RecordingActivityController {
    /// How often the figures are sent while recording; iOS may show them less often to save battery.
    static let every: TimeInterval = 10

    private var activity: Activity<RecordingActivityAttributes>?
    private var loop: Task<Void, Never>?
    private var last: RecordingActivityAttributes.ContentState?
    private var tidied = false
    /// What to show: read each time, so it follows the recorder, the link and the server's units as they change.
    var read: (() -> (PhoneRideRecorder, Units, Bool))?

    /// Call when the recorder's state or the link changes: starts, updates or ends the activity to match.
    func follow() {
        guard let (recorder, units, sharing) = read?() else { return }
        guard recorder.isRecording else {
            end()
            return
        }
        let state = Self.state(recorder: recorder, units: units, sharing: sharing)
        if activity == nil {
            tidy()
            start(recorder: recorder, state: state)
        } else {
            push(state, force: true)
        }
        if loop == nil {
            loop = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(Self.every))
                    guard let self, let (recorder, units, sharing) = self.read?(), recorder.isRecording else { return }
                    self.push(Self.state(recorder: recorder, units: units, sharing: sharing))
                }
            }
        }
    }

    static func state(recorder: PhoneRideRecorder, units: Units, sharing: Bool, now: Date = .now) -> RecordingActivityAttributes.ContentState {
        let sport = recorder.sport
        let elapsed = recorder.clock.elapsed(at: now)
        let distance = sport.usesGPS ? recorder.tracker.distance : recorder.session.distance
        let speed = recorder.state == .recording ? (sport.usesGPS ? recorder.tracker.currentSpeed : recorder.session.latest?.speed ?? 0) : 0
        return .init(distance: sport.hasDistance ? units.distance(metres: distance, sport: sport) : nil,
                     rate: sport.hasDistance && speed > 0 ? units.rate(metresPerSecond: speed, sport: sport) : nil,
                     rateCaption: Units.rateCaption(sport),
                     heartRate: recorder.liveSensors(at: now)?.heartRate,
                     timerStart: now.addingTimeInterval(-elapsed),
                     pausedElapsed: recorder.state == .paused ? elapsed : nil,
                     sharing: sharing)
    }

    private func start(recorder: PhoneRideRecorder, state: RecordingActivityAttributes.ContentState) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let attributes = RecordingActivityAttributes(sport: recorder.sport.title, symbol: recorder.sport.systemImage)
        activity = try? Activity.request(attributes: attributes, content: .init(state: state, staleDate: nil))
        last = state
    }

    /// One left on the Lock Screen by an app that was ended mid-recording: the recording is recovered on the Record screen, not live.
    private func tidy() {
        guard !tidied else { return }
        tidied = true
        for old in Activity<RecordingActivityAttributes>.activities { Self.end(id: old.id) }
    }

    /// Sent when anything shown has changed; `force` (a pause, the link) even within `every` of the last.
    private func push(_ state: RecordingActivityAttributes.ContentState, force: Bool = false) {
        guard let activity, state != last else { return }
        // The clock's start moves by a fraction of a second between reads; only a pause or resume moves it really.
        if !force, let last, Self.sameApartFromTheClock(last, state), abs(last.timerStart.timeIntervalSince(state.timerStart)) < 2 { return }
        last = state
        let id = activity.id
        Task.detached {
            for a in Activity<RecordingActivityAttributes>.activities where a.id == id { await a.update(.init(state: state, staleDate: nil)) }
        }
    }

    static func sameApartFromTheClock(_ a: RecordingActivityAttributes.ContentState, _ b: RecordingActivityAttributes.ContentState) -> Bool {
        var b = b
        b.timerStart = a.timerStart
        return a == b
    }

    private func end() {
        loop?.cancel()
        loop = nil
        guard let activity else { return }
        self.activity = nil
        last = nil
        Self.end(id: activity.id)
    }

    /// An Activity isn't Sendable, so the task finds it again by its id rather than taking it along.
    private nonisolated static func end(id: String) {
        Task.detached {
            for a in Activity<RecordingActivityAttributes>.activities where a.id == id { await a.end(nil, dismissalPolicy: .immediate) }
        }
    }
}
