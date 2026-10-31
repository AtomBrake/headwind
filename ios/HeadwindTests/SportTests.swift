import Foundation
import Testing
@testable import Headwind

/// A straight track north at a steady speed, one fix per second (~5 m apart).
private func track(from start: Date = Date(timeIntervalSince1970: 1_760_000_000), seconds: Int) -> [RidePoint] {
    (0..<seconds).map { i in
        RidePoint(time: start.addingTimeInterval(Double(i)), lat: 51.5 + Double(i) * 5 / 111_195.0, lon: -0.1, accuracy: 5, speed: 5)
    }
}

private func tempJournal() -> RideJournal {
    RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "journal-\(UUID().uuidString).jsonl"))
}

private func tempDefaults() -> UserDefaults {
    let name = "headwind-tests-\(UUID().uuidString)"
    let d = UserDefaults(suiteName: name)!
    d.removePersistentDomain(forName: name)
    return d
}

private let start = Date(timeIntervalSince1970: 1_760_000_000)

struct SportTests {
    @Test func gpxTypesAreWhatTheServerParserMaps() {
        // services/parser.py _SPORT_MAP: cycling → Ride, ebike → EBikeRide, running → Run, walking → Walk, hiking → Hike, swimming → Swim
        let gps = Sport.allCases.filter(\.usesGPS)
        #expect(gps.map(\.gpxType) == ["cycling", "ebike", "running", "walking", "hiking", "swimming"])
        #expect(gps.map(\.serverSport) == ["Ride", "EBikeRide", "Run", "Walk", "Hike", "Swim"])
        // The timed-only ones are services/manual_activity.SPORTS
        #expect(Sport.allCases.filter { !$0.usesGPS }.map(\.serverSport) == ["VirtualRide", "VirtualRun", "Swim", "Strength", "HIIT", "Yoga"])
        #expect(!Sport.phoneSports.contains(.poolSwim) && !Sport.phoneSports.contains(.openWaterSwim))
        let gpx = String(decoding: GPXWriter.gpx(segments: [track(seconds: 2)],
                                                 summary: RideSummary(start: start, distance: 5, movingTime: 1, elapsedTime: 1, elevationGain: 0, sport: .ebike)),
                         as: UTF8.self)
        #expect(gpx.contains("<type>ebike</type>"))
    }

    @Test func namesBySport() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let morning = Date(timeIntervalSince1970: Double(1_760_000_000 - 1_760_000_000 % 86_400) + 7 * 3600)
        #expect(GPXWriter.rideName(start: morning, sport: .run, calendar: cal) == "Morning Run")
        #expect(GPXWriter.rideName(start: morning, sport: .ebike, calendar: cal) == "Morning E-bike Ride")
        #expect(GPXWriter.rideName(start: morning, calendar: cal) == "Morning Ride")
    }

    @Test func unknownSportsAreRides() {
        #expect(Sport(stored: nil) == .ride)
        #expect(Sport(stored: "Kitesurf") == .ride)
        #expect(Sport(stored: "Hike") == .hike)
    }

    @Test func paceOnFoot() {
        #expect(Units(system: "metric").pace(metresPerSecond: 1000.0 / 332) == "5:32 /km")
        #expect(Units(system: "imperial").pace(metresPerSecond: 1609.344 / 600) == "10:00 /mi")
        #expect(Units(system: "metric").pace(metresPerSecond: 0) == "– /km")      // standing still
        #expect(Units(system: "metric").rate(metresPerSecond: 5, sport: .ride) == "18.0 km/h")
        #expect(Units.rateCaption(.walk, average: true) == "Avg pace")
    }
}

struct BikeTests {
    let bikes = [Bike(id: 1, name: "Roadie", kind: "road", isDefault: true), Bike(id: 2, name: "Zappy", kind: "ebike", isDefault: false)]

    @Test func picksTheLastChoiceThenTheDefault() {
        #expect(Bike.pick(2, from: bikes) == 2)
        #expect(Bike.pick(9, from: bikes) == 1)       // since deleted or archived on the server
        #expect(Bike.pick(nil, from: bikes) == 1)
        #expect(Bike.pick(nil, from: [Bike(id: 3, name: "Spare")]) == nil)   // no default: no bike
    }

    @Test func decodesPingAndRoundTripsToTheWatch() throws {
        let json = #"{"ok":true,"units":"metric","bikes":[{"id":1,"name":"Roadie","kind":"road","is_default":true}]}"#
        let ping = try JSONDecoder.headwind.decode(PingInfo.self, from: Data(json.utf8))
        #expect(ping.bikes == [bikes[0]])
        #expect(Bike(dictionary: bikes[1].dictionary) == bikes[1])
        // An older server's ping has no bikes.
        #expect(try JSONDecoder.headwind.decode(PingInfo.self, from: Data(#"{"ok":true}"#.utf8)).bikes == nil)
    }
}

struct SportStorageTests {
    @Test func summaryCarriesSportAndBikeToThePhone() throws {
        let s = RideSummary(start: start, distance: 5_000, movingTime: 1_500, elapsedTime: 1_600, elevationGain: 30, sport: .ebike, bikeId: 2)
        #expect(RideSummary(dictionary: s.dictionary) == s)
        #expect(try JSONDecoder().decode(RideSummary.self, from: JSONEncoder().encode(s)) == s)
        // On foot there's no bike.
        #expect(RideSummary(start: start, distance: 1, movingTime: 1, elapsedTime: 1, elevationGain: 0, sport: .walk, bikeId: 2).bikeId == nil)
    }

    @Test func recordingsSavedBeforeSportsAreRides() throws {
        let old = #"{"start":782000000,"distance":1000,"movingTime":200,"elapsedTime":210,"elevationGain":5}"#
        let s = try JSONDecoder().decode(RideSummary.self, from: Data(old.utf8))
        #expect(s.sport == .ride && s.bikeId == nil && s.distance == 1000)
        #expect(RideSummary(dictionary: ["start": 1.0, "distance": 2.0])?.sport == .ride)   // an older Watch app's metadata
    }

    @Test func journalKeepsTheSportAndBike() throws {
        let journal = tempJournal()
        defer { journal.clear() }
        let points = track(seconds: 3)
        journal.begin(start: points[0].time, sport: .run)
        for p in points { journal.append(p) }
        let r = try #require(journal.load())
        #expect(r.sport == .run && r.bikeId == nil && r.segments.map(\.count) == [3])

        journal.begin(start: points[0].time, sport: .ebike, bikeId: 7)
        for p in points { journal.append(p) }
        #expect(journal.load()?.bikeId == 7)
    }

    @Test func aJournalFromBeforeSportsIsARide() throws {
        let journal = tempJournal()
        defer { journal.clear() }
        let points = track(seconds: 2)
        let enc = JSONEncoder()
        enc.dateEncodingStrategy = .millisecondsSince1970
        var lines = [#"{"start":1760000000000}"#]
        for p in points { lines.append(#"{"p":"# + String(decoding: try enc.encode(p), as: UTF8.self) + "}") }
        try Data((lines.joined(separator: "\n") + "\n").utf8).write(to: journal.url)
        #expect(journal.load()?.sport == .ride)
    }

    @Test func onePointIsNothingToRecover() {
        let journal = tempJournal()
        defer { journal.clear() }
        journal.begin(start: start, sport: .walk)
        journal.append(track(seconds: 1)[0])
        #expect(journal.load() == nil)   // the server would refuse it (422) on every retry
    }

    @MainActor
    @Test func recoveredRideKeepsItsSport() throws {
        let journal = tempJournal()
        defer { journal.clear() }
        let points = track(seconds: 10)
        journal.begin(start: points[0].time, sport: .hike)
        for p in points { journal.append(p) }
        let recorder = PhoneRideRecorder(journal: journal, choices: RecordChoices(defaults: tempDefaults()))
        let (file, summary) = try recorder.saveRecovered { (gpx: Data?, s: RideSummary) throws(AppError) -> (Data?, RideSummary) in (gpx, s) }
        let gpx = try #require(file)
        #expect(summary.sport == .hike)
        #expect(String(decoding: gpx, as: UTF8.self).contains("<type>hiking</type>"))
        #expect(String(decoding: gpx, as: UTF8.self).contains("Hike</name>"))
    }

    @MainActor
    @Test func theSportChoiceIsRemembered() {
        let defaults = tempDefaults()
        let recorder = PhoneRideRecorder(journal: tempJournal(), choices: RecordChoices(defaults: defaults))
        #expect(recorder.sport == .ride)
        recorder.choose(sport: .walk)
        recorder.choose(bike: 4)
        let next = PhoneRideRecorder(journal: tempJournal(), choices: RecordChoices(defaults: defaults))
        #expect(next.sport == .walk && next.chosenBike == 4)
    }
}

struct UploadRoutingTests {
    private func saved(_ sport: Sport, bike: Int? = nil) -> SavedRide {
        SavedRide(id: UUID(), summary: RideSummary(start: start, distance: 1, movingTime: 1, elapsedTime: 1, elevationGain: 0,
                                                   sport: sport, bikeId: bike),
                  source: .phone, status: .pending)
    }

    @Test func ridesGoToRidesWithTheirBike() {
        #expect(RideStore.destination(saved(.ride)).path == "rides")
        #expect(RideStore.destination(saved(.ride)).fields.isEmpty)        // the server gives it the default bike
        #expect(RideStore.destination(saved(.ebike, bike: 2)).fields == ["bike_id": "2"])
    }

    @Test func onFootGoesToWorkoutsWithItsSport() {
        let walk = saved(.walk)
        let d = RideStore.destination(walk)
        #expect(d.path == "workouts")
        #expect(d.fields["sport"] == "Walk")
        #expect(d.fields["client_id"] == walk.id.uuidString)               // a retry finds the first upload
        #expect(d.fields["name"]?.hasSuffix("Walk") == true)
    }

    @Test func refusedRecordingsAreNotRetried() {
        #expect(AppError.serverError(status: 422, message: "could not parse").isRejection)
        #expect(AppError.serverError(status: 413, message: nil).isRejection)
        #expect(!AppError.serverError(status: 500, message: nil).isRejection)
        #expect(!AppError.serverError(status: 409, message: "no rider").isRejection)
    }
}

struct TodayTitleTests {
    @Test func theServersDateIsALocalDay() {
        var newYork = Calendar(identifier: .gregorian)
        newYork.timeZone = TimeZone(identifier: "America/New_York")!
        // 20:00 on 17 October in New York is already the 18th in UTC.
        let evening = newYork.date(from: DateComponents(year: 2026, month: 10, day: 17, hour: 20))!
        #expect(TodayView.title(for: "2026-10-17", now: evening, calendar: newYork) == "Today")
        #expect(TodayView.title(for: "2026-10-16", now: evening, calendar: newYork).contains("16"))
        var tokyo = Calendar(identifier: .gregorian)
        tokyo.timeZone = TimeZone(identifier: "Asia/Tokyo")!
        let early = tokyo.date(from: DateComponents(year: 2026, month: 10, day: 18, hour: 1))!
        #expect(TodayView.title(for: "2026-10-18", now: early, calendar: tokyo) == "Today")
        #expect(TodayView.title(for: "nonsense", now: early, calendar: tokyo) == "Today")
    }
}

@MainActor
struct SwitchServerTests {
    @Test func aLinkThatFailsKeepsTheWorkingPairing() async {
        let current = Pairing(server: URL(string: "https://bike.example.com")!, token: "hw_TestOnlyNotARealToken0123456789abcdefghij")
        let store = MemoryPairingStore(current)
        let session = Session(store: store, defaults: tempDefaults())
        // Nothing listens on port 1, so the check fails and nothing is replaced.
        await #expect(throws: AppError.self) {
            try await session.pair(link: "headwind://pair?u=https%3A%2F%2F127.0.0.1%3A1&t=hw_AnotherTestToken0123456789abcdefghij")
        }
        #expect(session.pairing == current)
        #expect(store.pairing == current)
    }
}

struct TimedSessionTests {
    @MainActor
    @Test func aStrengthSessionIsATimerThatNeedsAMinute() throws {
        let recorder = PhoneRideRecorder(journal: tempJournal(), choices: RecordChoices(defaults: tempDefaults()))
        recorder.choose(sport: .strength)
        recorder.start()
        #expect(recorder.isRecording)
        #expect(throws: AppError.self) {
            try recorder.finish { (_: Data?, _: RideSummary) throws(AppError) -> Void in }
        }
        #expect(recorder.isRecording)     // too short: still going, nothing lost
        recorder.discard()
    }

    @Test func aSessionsJournalKeepsItsProgress() throws {
        let journal = tempJournal()
        defer { journal.clear() }
        journal.begin(start: start, sport: .poolSwim)
        journal.note(.init(at: start.addingTimeInterval(1800), active: 1750, distance: 1200, calories: 300, heartRate: 128))
        let r = try #require(journal.load())
        let s = RideJournal.summary(of: r)
        #expect(s.sport == .poolSwim && s.movingTime == 1750 && s.distance == 1200 && s.calories == 300 && s.averageHeartRate == 128)
    }

    @Test func aSessionGoesToActivitiesWithItsOffset() {
        let body = Uploader.sessionBody(summary: .session(start: start, elapsed: 3600, sport: .yoga, calories: 150), id: UUID(), name: "Yoga")
        #expect(body.sport == "Yoga" && body.duration_s == 3600 && body.distance_m == nil && body.calories == 150)
        #expect(ISO8601DateFormatter().date(from: body.start) == start)
    }

    @Test func powerAndCadenceGoInTheGPX() {
        let points = track(seconds: 3).map { var p = $0; p.power = 210; p.cadence = 88; p.hr = 140; return p }
        let gpx = String(decoding: GPXWriter.gpx(segments: [points], name: "x"), as: UTF8.self)
        #expect(gpx.contains("<power>210</power>") && gpx.contains("<gpxtpx:cad>88</gpxtpx:cad>") && gpx.contains("<gpxtpx:hr>140</gpxtpx:hr>"))
        var t = RideTracker()
        for p in points { t.add(p) }
        #expect(t.averagePower == 210 && t.averageCadence == 88)
    }

    @Test func swimsReadPer100Metres() {
        #expect(Units(system: "metric").swimPace(metresPerSecond: 100.0 / 112) == "1:52 /100m")
        #expect(Units(system: "metric").rate(metresPerSecond: 1, sport: .poolSwim).hasSuffix("/100m"))
        #expect(Units.rateCaption(.openWaterSwim) == "Pace")
    }
}

@MainActor
struct WatchRecordingTests {
    @Test func aWatchRideKeepsItsIdSoItsUploadedOnce() throws {
        let dir = FileManager.default.temporaryDirectory.appending(path: "store-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let store = RideStore(directory: dir)
        let id = UUID()
        let summary = RideSummary.session(start: start, elapsed: 1200, sport: .poolSwim, distance: 800)
        let first = try store.addSession(summary: summary, source: .watch, id: id)
        let again = try store.addSession(summary: summary, source: .watch, id: id)   // the Watch sent it twice
        #expect(first.id == id && again.id == id && store.rides.count == 1)
        #expect(store.gpxURL(for: first) == nil && !first.hasTrack && first.kind == "workout")
        #expect(RideStore.destination(first).fields["client_id"] == id.uuidString)
    }
}

struct HealthSleepTests {
    @Test func overlappingSleepIsCountedOnceAndDatedToTheMorning() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "Europe/London")!
        let d = { (day: Int, h: Int, m: Int) in cal.date(from: DateComponents(year: 2026, month: 10, day: day, hour: h, minute: m))! }
        // The Watch and a sleep app both recorded the same night, overlapping; then a nap the next afternoon.
        let nights = HealthSync.nights([(d(19, 23, 0), d(20, 3, 0)), (d(20, 2, 0), d(20, 6, 30)), (d(20, 14, 0), d(20, 14, 30))], calendar: cal)
        #expect(nights == [HealthDay(date: "2026-10-20", metric: "sleep_hours", value: 8.0)])
        #expect(HealthSync.clientID(UUID(uuidString: "E621E1F8-C36C-495A-93FC-0C247A3E6E5F")!) == "ah_e621e1f8-c36c-495a-93fc-0c247a3e6e5f")
    }
}
