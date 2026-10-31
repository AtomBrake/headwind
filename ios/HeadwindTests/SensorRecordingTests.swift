import Foundation
import Testing
@testable import Headwind

/// Stands in for Bluetooth: whatever readings the test sets.
@MainActor
private final class FakeSensors: SensorFeed {
    var hasPaired = true
    var now = SensorReadings()
    private(set) var uses: Set<SensorUse> = []
    var onReading: (() -> Void)?

    func readings(at date: Date) -> SensorReadings { now }
    func use(_ use: SensorUse) { uses.insert(use) }
    func stopUsing(_ use: SensorUse) { uses.remove(use) }
}

private func journal() -> RideJournal {
    RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "sensor-recording-\(UUID().uuidString).jsonl"))
}

private func defaults() -> UserDefaults {
    let name = "sensor-recording-\(UUID().uuidString)"
    let d = UserDefaults(suiteName: name)!
    d.removePersistentDomain(forName: name)
    return d
}

@MainActor
struct SensorRecordingTests {
    @Test func anIndoorRideTakesASampleEverySecond() throws {
        let file = journal()
        defer { file.clear() }
        let sensors = FakeSensors()
        let trainer = UUID()
        let recorder = PhoneRideRecorder(journal: file, choices: RecordChoices(defaults: defaults()), sensors: sensors)
        recorder.choose(sport: .indoorRide)
        recorder.start(bike: 2)
        #expect(sensors.uses.contains(.recording))
        let start = Date()
        for s in 1...120 {
            sensors.now = SensorReadings(heartRate: 140, power: s.isMultiple(of: 2) ? 250 : 150, cadence: 90, speed: 8,
                                         distance: 1000 + Double(s) * 8, distanceSource: trainer)
            recorder.tick(at: start.addingTimeInterval(Double(s)))
            recorder.tick(at: start.addingTimeInterval(Double(s) + 0.3))   // another reading within the second: no second sample
        }
        #expect(recorder.session.samples.count == 120)
        #expect(recorder.session.distance == 952)        // from the first reading on: 119 steps of 8 m
        #expect(recorder.session.averagePower == 200)

        // Killed here: the journal has every second, and the next launch offers the ride with its sensors' averages.
        let next = PhoneRideRecorder(journal: file, choices: RecordChoices(defaults: defaults()))
        let recovered = try #require(next.recovered)
        #expect(recovered.samples.count == 120)
        let summary = RideJournal.summary(of: recovered)
        #expect(summary.sport == .indoorRide && summary.bikeId == 2)
        #expect(summary.distance == 952)
        #expect(summary.averageHeartRate == 140 && summary.averagePower == 200 && summary.averageCadence == 90)
        recorder.discard()
        #expect(!sensors.uses.contains(.recording))
    }

    @Test func pausedSecondsAreNotSampled() {
        let file = journal()
        defer { file.clear() }
        let sensors = FakeSensors()
        let recorder = PhoneRideRecorder(journal: file, choices: RecordChoices(defaults: defaults()), sensors: sensors)
        recorder.choose(sport: .indoorRide)
        recorder.start()
        let start = Date()
        let source = UUID()
        func ride(_ s: Int, distance: Double) {
            sensors.now = SensorReadings(power: 200, distance: distance, distanceSource: source)
            recorder.tick(at: start.addingTimeInterval(Double(s)))
        }
        ride(1, distance: 0)
        ride(2, distance: 10)
        recorder.pause()
        ride(3, distance: 20)
        ride(4, distance: 30)
        recorder.resume()
        ride(5, distance: 40)
        ride(6, distance: 50)
        #expect(recorder.session.samples.count == 4)
        #expect(recorder.session.distance == 20)          // the 20 m ridden while paused don't count
        recorder.discard()
    }

    @Test func aRunTakesOnlyHeartRateFromTheSensors() throws {
        let sensors = FakeSensors()
        sensors.now = SensorReadings(heartRate: 150, power: 300, cadence: 85, speed: 3, distance: 10, distanceSource: UUID())
        let recorder = PhoneRideRecorder(journal: journal(), choices: RecordChoices(defaults: defaults()), sensors: sensors)
        recorder.choose(sport: .treadmill)
        #expect(recorder.liveSensors() == SensorReadings(heartRate: 150))
        recorder.start()
        recorder.tick(at: Date().addingTimeInterval(1))
        let sample = try #require(recorder.session.latest)
        #expect(sample.hr == 150 && sample.power == nil && sample.distance == nil)
        recorder.discard()
    }

    @Test func noSensorsNoSamples() {
        let sensors = FakeSensors()
        sensors.hasPaired = false
        let recorder = PhoneRideRecorder(journal: journal(), choices: RecordChoices(defaults: defaults()), sensors: sensors)
        recorder.choose(sport: .strength)
        #expect(recorder.liveSensors() == nil)
        recorder.start()
        recorder.tick(at: Date().addingTimeInterval(1))
        #expect(recorder.session.isEmpty)
        recorder.discard()
    }

    @Test func theRecordScreenHoldsTheSensors() {
        let sensors = FakeSensors()
        let recorder = PhoneRideRecorder(journal: journal(), choices: RecordChoices(defaults: defaults()), sensors: sensors)
        recorder.warmUp()
        #expect(sensors.uses == [.recordScreen])
        recorder.coolDown()
        #expect(sensors.uses.isEmpty)
    }
}
