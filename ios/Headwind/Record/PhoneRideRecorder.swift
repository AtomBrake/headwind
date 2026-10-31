import CoreLocation
import Foundation
import Observation
import UIKit

/// Records a ride, walk, run or hike with the iPhone's GPS. Keeps running with the screen locked (UIBackgroundModes: location,
/// started from the foreground with When-In-Use permission), journals every fix so a crash loses nothing,
/// and reports live position to the server's /api/v1/live for Home Assistant, as the Android app does.
///
/// A sport without GPS (an indoor ride, a treadmill, strength, HIIT, yoga) is a timer: no location at all, and a note in the journal every
/// `sessionNoteInterval` so a crash keeps all but the last few seconds.
///
/// Paired Bluetooth sensors (`SensorManager`) are connected while the Record screen shows and while recording. Their readings go on
/// each fix (heart rate always; power and cadence on a ride), and are read every second besides, for the live display and for an
/// indoor ride's distance from a trainer or wheel sensor (`sensorTally`).
@MainActor
@Observable
final class PhoneRideRecorder {
    enum State: Equatable { case idle, recording, paused }

    private(set) var state: State = .idle
    private(set) var tracker = RideTracker()
    private(set) var clock = ActiveClock()
    /// Latest fix, kept even when idle, for the map and the GPS-ready indicator.
    private(set) var lastLocation: CLLocation?
    private(set) var authorization: CLAuthorizationStatus
    /// A ride left in the journal by a crash or a killed app, waiting for the user to save or discard it.
    private(set) var recovered: RideJournal.Recovered?
    /// The sport for the next recording, or the one recording now. Chosen before Start, remembered for next time.
    private(set) var sport: Sport
    /// The bike last chosen in the picker (it may since have gone from the server's list: see Bike.pick).
    private(set) var chosenBike: Int?
    /// The bike the recording in progress is on.
    private(set) var bikeId: Int?
    /// The sensors' latest readings, and the distance they've given while recording (not while paused).
    private(set) var sensorTally = SensorTally()

    private let feed = LocationFeed()
    private let journal: RideJournal
    private let choices: RecordChoices
    /// Whether the Record screen is showing, so finishing a ride goes back to the map's foreground feed rather than off.
    private var onScreen = false
    private var lastLivePost = Date.distantPast
    private var liveTask: Task<Void, Never>?
    private var noteTask: Task<Void, Never>?
    /// Nil in previews and tests: no sensors.
    private let sensors: SensorManager?
    private var sensorTask: Task<Void, Never>?
    /// Set by the app: posts JSON to /api/v1/live. Nil (e.g. in previews) skips live updates.
    var postLive: ((LiveUpdate) async -> Void)?

    static let livePostInterval: TimeInterval = 15
    static let sessionNoteInterval: Duration = .seconds(30)

    init(journal: RideJournal = .standard, choices: RecordChoices = RecordChoices(), sensors: SensorManager? = nil) {
        self.journal = journal
        self.choices = choices
        self.sensors = sensors
        sport = choices.sport
        chosenBike = choices.bikeId
        authorization = feed.manager.authorizationStatus
        recovered = journal.load()
        feed.onLocations = { [weak self] in self?.received($0) }
        feed.onAuthorization = { [weak self] in self?.authorization = $0 }
    }

    var isRecording: Bool { state != .idle }

    /// Good enough to start: a recent fix within the tracker's accuracy limit.
    var gpsReady: Bool {
        guard let l = lastLocation else { return false }
        return l.horizontalAccuracy >= 0 && l.horizontalAccuracy <= RideTracker.maxAccuracy && -l.timestamp.timeIntervalSinceNow < 10
    }

    /// Start watching location for the map before a ride (foreground only). Mid-ride the feed is already
    /// running in the background, and restarting it here would switch that off.
    func warmUp() {
        if authorization == .notDetermined { feed.manager.requestWhenInUseAuthorization() }
        onScreen = true
        sensors?.hold(.recordScreen)        // readings before Start, as a head unit shows them
        startSensorClock()
        guard state == .idle else { return }
        feed.start(background: false)
    }

    func coolDown() {
        onScreen = false
        sensors?.release(.recordScreen)
        if state == .idle {
            feed.stop()
            stopSensorClock()
        }
    }

    /// Locked once recording: a ride can't become a run halfway.
    func choose(sport: Sport) {
        guard state == .idle else { return }
        self.sport = sport
        choices.sport = sport
    }

    func choose(bike: Int?) {
        guard state == .idle else { return }
        chosenBike = bike
        choices.bikeId = bike
    }

    /// Refuses while a recovered ride is waiting: the new ride's journal would replace the one it lives in.
    /// `bike` is the one to ride on (Bike.pick of the picker's choice); ignored on foot.
    func start(bike: Int? = nil) {
        guard state == .idle, recovered == nil else { return }
        tracker = RideTracker()
        bikeId = sport.isRide ? bike : nil
        let now = Date()
        clock.start(at: now)
        journal.begin(start: now, sport: sport, bikeId: bikeId)
        state = .recording
        sensors?.hold(.recording)
        sensorTally = SensorTally()
        readSensors()                       // where the sensors' distance stands at Start
        startSensorClock()
        if sport.usesGPS {
            if authorization == .notDetermined { feed.manager.requestWhenInUseAuthorization() }
            feed.start(background: true)
        } else {
            feed.stop()                     // a timer needs no location, and shouldn't keep the GPS on
            noteTask = Task { [weak self] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: Self.sessionNoteInterval)
                    self?.noteSession()
                }
            }
        }
        sendLive(force: true)
    }

    private func noteSession() {
        guard state != .idle, !sport.usesGPS else { return }
        journal.note(.init(at: .now, active: clock.elapsed()))
    }

    func pause() {
        guard state == .recording else { return }
        state = .paused
        tracker.pause()
        clock.pause()
        noteSession()
    }

    func resume() {
        guard state == .paused else { return }
        state = .recording
        tracker.resume()
        clock.resume()
        if sport.usesGPS { journal.newSegment() }
    }

    /// Hands the ride, as GPX plus its summary (the summary alone for a timed-only session), to `keep` (which stores it), and only once that
    /// succeeds stops recording and clears the journal. Throws, and keeps recording, if there's no usable track yet (or under a minute of a
    /// session) or `keep` fails, so the user can retry or discard rather than lose the ride.
    func finish<T>(into keep: (Data?, RideSummary) throws(AppError) -> T) throws(AppError) -> T {
        guard state != .idle, let start = clock.startedAt else { throw .rideTooShort }
        guard sport.usesGPS else {
            let elapsed = clock.elapsed()
            guard elapsed >= RideSummary.minimumSession else { throw .sessionTooShort }
            let kept = try keep(nil, .session(start: start, elapsed: elapsed, sport: sport, bikeId: bikeId))
            endRecording()
            return kept
        }
        guard tracker.pointCount >= 2 else { throw .rideTooShort }
        let summary = RideSummary(start: start, tracker: tracker, elapsed: clock.elapsed(), sport: sport, bikeId: bikeId)
        let kept = try keep(GPXWriter.gpx(segments: tracker.segments, summary: summary), summary)
        endRecording()
        return kept
    }

    func discard() {
        endRecording()
    }

    /// Like `finish(into:)` for the recovered ride: it stays recovered, journal and all, unless `keep` succeeds.
    /// One with too little track to save, as `finish` would refuse, is discarded.
    func saveRecovered<T>(into keep: (Data?, RideSummary) throws(AppError) -> T) throws(AppError) -> T {
        guard let r = recovered else { throw .rideTooShort }
        let summary = RideJournal.summary(of: r)
        if r.session == nil {
            guard RideTracker(segments: r.segments).pointCount >= 2 else {
                discardRecovered()
                throw .rideTooShort
            }
        }
        let kept = try keep(r.session == nil ? GPXWriter.gpx(segments: r.segments, summary: summary) : nil, summary)
        recovered = nil
        journal.clear()
        return kept
    }

    func discardRecovered() {
        recovered = nil
        journal.clear()
    }

    /// Back to the foreground feed if the Record screen is still showing, so the map keeps following; off otherwise.
    private func endRecording() {
        state = .idle
        noteTask?.cancel()
        noteTask = nil
        journal.clear()
        sensors?.release(.recording)
        if onScreen {
            feed.start(background: false)
        } else {
            feed.stop()
            stopSensorClock()
        }
        sendLive(force: true)
    }

    private func startSensorClock() {
        guard sensors != nil, sensorTask == nil else { return }
        sensorTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                guard let self else { return }
                self.readSensors()
            }
        }
    }

    private func stopSensorClock() {
        sensorTask?.cancel()
        sensorTask = nil
    }

    /// The sensors' readings now, kept in `sensorTally` (only when they've changed, so an idle screen isn't redrawn every second).
    @discardableResult
    private func readSensors() -> SensorReadings {
        guard let sensors else { return .none }
        let readings = sensors.readings()
        var tally = sensorTally
        tally.update(readings, counting: state == .recording)
        if tally != sensorTally { sensorTally = tally }
        return readings
    }

    private func received(_ locations: [CLLocation]) {
        guard let latest = locations.last else { return }
        lastLocation = latest
        guard state == .recording, sport.usesGPS else { return }
        // A batch gets the readings of now: while recording, iOS delivers fixes as they come, so that's the last second or so.
        let readings = readSensors()
        let power = sport.isRide ? readings.power : nil, cadence = sport.isRide ? readings.cadence : nil
        for location in locations where location.timestamp >= (clock.startedAt ?? .distantPast) {
            let point = RidePoint(location, hr: readings.heartRate, power: power, cadence: cadence)
            if tracker.add(point) { journal.append(point) }
        }
        sendLive()
    }

    private func sendLive(force: Bool = false) {
        guard let postLive, force || Date().timeIntervalSince(lastLivePost) >= Self.livePostInterval else { return }
        lastLivePost = Date()
        UIDevice.current.isBatteryMonitoringEnabled = true
        let battery = UIDevice.current.batteryLevel
        let l = lastLocation
        let update = LiveUpdate(
            state: state == .idle ? "idle" : "riding",   // services/live.py's state, whatever the sport
            lat: l?.coordinate.latitude, lng: l?.coordinate.longitude,
            speed_mps: state == .recording ? tracker.currentSpeed : 0,
            distance_m: tracker.distance, elapsed_s: Int(clock.elapsed()),
            alt_m: l.flatMap { $0.verticalAccuracy >= 0 ? $0.altitude : nil },
            accuracy_m: l?.horizontalAccuracy,
            sport: sport.rawValue,
            battery_pct: battery >= 0 ? Int(battery * 100) : nil
        )
        // Fire and forget: Home Assistant missing one update doesn't matter, the ride itself is journalled.
        liveTask = Task { await postLive(update) }
    }
}

/// Body of POST /api/v1/live (see services/live.py clean()).
struct LiveUpdate: Encodable, Sendable {
    var state: String
    var lat: Double?
    var lng: Double?
    var speed_mps: Double
    var distance_m: Double
    var elapsed_s: Int
    var alt_m: Double?
    var accuracy_m: Double?
    var sport: String
    var battery_pct: Int?
}

/// CLLocationManager wrapper; delegate callbacks arrive on the main thread because the manager is made there.
@MainActor
private final class LocationFeed: NSObject, CLLocationManagerDelegate {
    let manager = CLLocationManager()
    var onLocations: (([CLLocation]) -> Void)?
    var onAuthorization: ((CLAuthorizationStatus) -> Void)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyBest
        manager.distanceFilter = kCLDistanceFilterNone
        manager.activityType = .fitness
        manager.pausesLocationUpdatesAutomatically = false
    }

    func start(background: Bool) {
        manager.allowsBackgroundLocationUpdates = background
        manager.showsBackgroundLocationIndicator = background
        manager.startUpdatingLocation()
    }

    func stop() {
        manager.stopUpdatingLocation()
        manager.allowsBackgroundLocationUpdates = false
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        MainActor.assumeIsolated { onLocations?(locations) }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        MainActor.assumeIsolated { onAuthorization?(status) }
    }
}
