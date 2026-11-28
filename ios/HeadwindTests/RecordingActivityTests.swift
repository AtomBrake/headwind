import Foundation
import Testing
@testable import Headwind

/// The recording's Live Activity (RecordingActivityController): what goes on the Lock Screen, and when it's worth sending again.
@MainActor
struct RecordingActivityTests {
    private func recorder(sport: Sport) -> PhoneRideRecorder {
        let name = "recording-activity-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        let r = PhoneRideRecorder(journal: RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "\(name).jsonl")),
                                  choices: RecordChoices(defaults: defaults))
        r.choose(sport: sport)
        return r
    }

    @Test func aRideShowsItsDistanceAndSpeedAndWhetherItsShared() {
        let r = recorder(sport: .ride)
        r.start()
        defer { r.discard() }
        let now = Date()
        let s = RecordingActivityController.state(recorder: r, units: Units(system: "metric"), sharing: true, now: now)
        #expect(s.distance == "0.0 km")
        #expect(s.rate == nil)                              // not moving yet
        #expect(s.rateCaption == Units.rateCaption(.ride))
        #expect(s.sharing)
        #expect(s.pausedElapsed == nil)
        #expect(abs(s.timerStart.timeIntervalSince(now.addingTimeInterval(-r.clock.elapsed(at: now)))) < 0.01)
    }

    @Test func pausedTheClockStandsStill() {
        let r = recorder(sport: .run)
        r.start()
        defer { r.discard() }
        r.pause()
        let s = RecordingActivityController.state(recorder: r, units: Units(system: "imperial"), sharing: false)
        #expect(s.pausedElapsed != nil)
        #expect(!s.sharing)
    }

    @Test func strengthHasNoDistance() {
        let r = recorder(sport: .strength)
        r.start()
        defer { r.discard() }
        let s = RecordingActivityController.state(recorder: r, units: Units(system: "metric"), sharing: false)
        #expect(s.distance == nil)
        #expect(s.rate == nil)
    }

    @Test func theClockMovingOnAloneIsntWorthSending() {
        let a = RecordingActivityAttributes.ContentState(distance: "1.0 km", rate: "20 km/h", rateCaption: "Speed", heartRate: 120,
                                                         timerStart: .now, pausedElapsed: nil, sharing: false)
        var b = a
        b.timerStart = a.timerStart.addingTimeInterval(0.3)
        #expect(RecordingActivityController.sameApartFromTheClock(a, b))
        b.distance = "1.1 km"
        #expect(!RecordingActivityController.sameApartFromTheClock(a, b))
    }

    @Test func thePausedClockReads() {
        #expect(RecordingActivityAttributes.ContentState.clock(75) == "1:15")
        #expect(RecordingActivityAttributes.ContentState.clock(3723) == "1:02:03")
    }
}
