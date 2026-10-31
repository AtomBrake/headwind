import Foundation
import Testing
@testable import Headwind

/// A straight ride north at a steady speed: one fix per second, ~0.000045° latitude ≈ 5 m.
private func ride(from start: Date = Date(timeIntervalSince1970: 1_760_000_000), seconds: Int, metresPerSecond: Double = 5,
                  lat: Double = 51.5, ele: ((Int) -> Double)? = nil, hr: Int? = nil) -> [RidePoint] {
    let degPerMetre = 1 / 111_195.0
    return (0..<seconds).map { i in
        RidePoint(time: start.addingTimeInterval(Double(i)), lat: lat + Double(i) * metresPerSecond * degPerMetre, lon: -0.1,
                  ele: ele?(i), accuracy: 5, speed: metresPerSecond, hr: hr)
    }
}

struct RideTrackerTests {
    @Test func accumulatesDistanceAndMovingTime() {
        var t = RideTracker()
        for p in ride(seconds: 61) { t.add(p) }
        #expect(abs(t.distance - 300) < 1)          // 60 intervals × 5 m
        #expect(t.movingTime == 60)
        #expect(abs(t.averageSpeed - 5) < 0.05)
        #expect(t.pointCount == 61)
    }

    @Test func standingStillIsNotMovingTime() {
        var t = RideTracker()
        let start = Date(timeIntervalSince1970: 1_760_000_000)
        for i in 0..<30 {
            t.add(RidePoint(time: start.addingTimeInterval(Double(i)), lat: 51.5, lon: -0.1, accuracy: 5, speed: 0))
        }
        #expect(t.movingTime == 0)
        #expect(t.distance < 1)
    }

    @Test func dropsInaccurateFixesAndGPSJumps() {
        var t = RideTracker()
        let points = ride(seconds: 3)
        t.add(points[0])
        var vague = points[1]; vague.accuracy = 120
        let keptVague = t.add(vague)
        var jump = points[1]; jump.lat += 0.01   // ~1.1 km in one second
        let keptJump = t.add(jump)
        let keptGood = t.add(points[2])
        #expect(!keptVague)
        #expect(!keptJump)
        #expect(keptGood)
        #expect(t.pointCount == 2)
    }

    @Test func climbingIgnoresJitter() {
        var t = RideTracker()
        // ±1 m noise on a flat road, then a steady 20 m climb.
        for p in ride(seconds: 40, ele: { $0 < 20 ? 100 + Double($0 % 2) : 100 + Double($0 - 20) }) { t.add(p) }
        #expect(t.elevationGain >= 15 && t.elevationGain <= 20)
    }

    @Test func pausesStartANewSegmentAndDontCountTheGap() {
        var t = RideTracker()
        let first = ride(seconds: 11)
        for p in first { t.add(p) }
        t.pause()
        let keptWhilePaused = t.add(ride(from: first.last!.time.addingTimeInterval(1), seconds: 1)[0])
        #expect(!keptWhilePaused)
        t.resume()
        // Resume 10 minutes and ~2 km further on: the gap must not become distance.
        let second = ride(from: first.last!.time.addingTimeInterval(600), seconds: 11, lat: 51.52)
        for p in second { t.add(p) }
        #expect(t.segments.count == 2)
        #expect(abs(t.distance - 100) < 1)
        #expect(t.movingTime == 20)
    }

    @Test func averagesHeartRate() {
        var t = RideTracker()
        for p in ride(seconds: 5, hr: 140) { t.add(p) }
        #expect(t.averageHeartRate == 140)
    }

    @Test func activeClockExcludesPauses() {
        var c = ActiveClock()
        let t0 = Date(timeIntervalSince1970: 0)
        c.start(at: t0)
        c.pause(at: t0.addingTimeInterval(60))
        c.resume(at: t0.addingTimeInterval(300))
        #expect(c.elapsed(at: t0.addingTimeInterval(330)) == 90)
    }
}

struct GPXWriterTests {
    @Test func writesWhatTheServerParserReads() throws {
        let points = ride(seconds: 3, ele: { _ in 42 }, hr: 151)
        let gpx = String(decoding: GPXWriter.gpx(segments: [Array(points[0..<2]), [points[2]]], name: "Evening <Ride> & co"), as: UTF8.self)
        #expect(gpx.contains("<type>cycling</type>"))                       // → sport Ride (services/parser.py _SPORT_MAP)
        #expect(gpx.contains("<name>Evening &lt;Ride&gt; &amp; co</name>"))
        #expect(gpx.components(separatedBy: "<trkseg>").count == 3)         // one per segment
        #expect(gpx.contains("<gpxtpx:hr>151</gpxtpx:hr>"))                 // parser looks for any element named hr
        #expect(gpx.contains("<ele>42.0</ele>"))
        #expect(gpx.contains("<time>2025-10-09T08:53:20Z</time>"))
        // Well-formed XML.
        let parser = XMLParser(data: Data(gpx.utf8))
        #expect(parser.parse())
    }

    @Test func namesRideByTimeOfDay() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let day = Date(timeIntervalSince1970: Double(1_760_000_000 - 1_760_000_000 % 86_400))
        #expect(GPXWriter.rideName(start: day.addingTimeInterval(7 * 3600), calendar: cal) == "Morning Ride")
        #expect(GPXWriter.rideName(start: day.addingTimeInterval(13 * 3600), calendar: cal) == "Afternoon Ride")
        #expect(GPXWriter.rideName(start: day.addingTimeInterval(18 * 3600), calendar: cal) == "Evening Ride")
        #expect(GPXWriter.rideName(start: day.addingTimeInterval(23 * 3600), calendar: cal) == "Night Ride")
    }
}

struct RideJournalTests {
    private func tempJournal() -> RideJournal {
        RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "journal-\(UUID().uuidString).jsonl"))
    }

    @Test func recoversSegmentsAfterACrash() throws {
        let journal = tempJournal()
        defer { journal.clear() }
        let points = ride(seconds: 4)
        journal.begin(start: points[0].time)
        journal.append(points[0])
        journal.append(points[1])
        journal.newSegment()
        journal.append(points[2])
        journal.append(points[3])
        // Simulate dying mid-write: a truncated last line.
        let handle = try FileHandle(forWritingTo: journal.url)
        try handle.seekToEnd()
        try handle.write(contentsOf: Data("{\"p\":{\"lat\":51.".utf8))
        try handle.close()

        let recovered = try #require(journal.load())
        #expect(recovered.start == points[0].time)
        #expect(recovered.segments.map(\.count) == [2, 2])
        #expect(recovered.segments[1][1] == points[3])
    }

    @Test func emptyJournalIsNothingToRecover() {
        let journal = tempJournal()
        defer { journal.clear() }
        #expect(journal.load() == nil)
        journal.begin(start: .now)
        #expect(journal.load() == nil)
    }
}

struct RideSummaryTests {
    @Test func roundTripsThroughWatchMetadata() {
        let s = RideSummary(start: Date(timeIntervalSince1970: 1_760_000_000), distance: 12_345, movingTime: 2_400,
                            elapsedTime: 2_700, elevationGain: 210, averageHeartRate: 138)
        #expect(RideSummary(dictionary: s.dictionary) == s)
    }
}

private func tempURL(_ name: String) -> URL {
    FileManager.default.temporaryDirectory.appending(path: "\(name)-\(UUID().uuidString)")
}

/// A journal holding a ride left behind by a crash.
private func crashedJournal() -> RideJournal {
    let journal = RideJournal(url: tempURL("journal").appendingPathExtension("jsonl"))
    let points = ride(seconds: 10)
    journal.begin(start: points[0].time)
    for p in points { journal.append(p) }
    return journal
}

private struct DiskFull: Error {}

@MainActor
struct PhoneRideRecorderTests {
    @Test func recoveredRideSurvivesAFailedSave() throws {
        let journal = crashedJournal()
        defer { journal.clear() }
        let recorder = PhoneRideRecorder(journal: journal)
        #expect(recorder.recovered != nil)

        #expect(throws: AppError.self) {
            try recorder.saveRecovered { (_: Data, _: RideSummary) throws(AppError) -> Void in
                throw .storage(underlying: DiskFull())
            }
        }
        #expect(recorder.recovered != nil)
        #expect(journal.load()?.segments.first?.count == 10)

        let kept = try recorder.saveRecovered { (gpx: Data, _: RideSummary) throws(AppError) -> Data in gpx }
        #expect(!kept.isEmpty)
        #expect(recorder.recovered == nil)
        #expect(!journal.exists)
    }

    @Test func startingWaitsForTheRecoveredRide() {
        let journal = crashedJournal()
        defer { journal.clear() }
        let recorder = PhoneRideRecorder(journal: journal)
        recorder.start()
        #expect(recorder.state == .idle)
        #expect(journal.load()?.segments.first?.count == 10)   // not replaced by a new ride's journal
    }
}

@MainActor
struct WatchInboxTests {
    @Test func ridesLeftInTheInboxAreStoredOnLaunch() throws {
        let inbox = tempURL("inbox"), recordings = tempURL("recordings")
        defer { try? FileManager.default.removeItem(at: inbox); try? FileManager.default.removeItem(at: recordings) }
        try FileManager.default.createDirectory(at: inbox, withIntermediateDirectories: true)
        let summary = RideSummary(start: Date(timeIntervalSince1970: 1_760_000_000), distance: 1_000, movingTime: 200,
                                  elapsedTime: 210, elevationGain: 5)
        let gpx = GPXWriter.gpx(segments: [ride(seconds: 3)], name: "Morning Ride")
        try gpx.write(to: inbox.appending(path: "a.gpx"))
        try JSONEncoder().encode(summary).write(to: inbox.appending(path: "a.json"))
        try gpx.write(to: inbox.appending(path: "b.gpx"))   // no summary beside it: still stored

        let store = RideStore(directory: recordings)
        _ = WatchBridge(store: store, inbox: inbox)

        #expect(store.rides.count == 2)
        #expect(store.rides.contains { $0.summary == summary && $0.source == .watch })
        #expect(try FileManager.default.contentsOfDirectory(atPath: inbox.path()).isEmpty)
        // And the index survives a relaunch.
        #expect(RideStore(directory: recordings).rides.count == 2)
    }
}
