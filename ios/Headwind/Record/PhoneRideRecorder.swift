import CoreLocation
import Foundation
import Observation
import UIKit

/// Records a ride with the iPhone's GPS. Keeps running with the screen locked (UIBackgroundModes: location,
/// started from the foreground with When-In-Use permission), journals every fix so a crash loses nothing,
/// and reports live position to the server's /api/v1/live for Home Assistant, as the Android app does.
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
    private(set) var recovered: (start: Date, segments: [[RidePoint]])?

    private let feed = LocationFeed()
    private let journal: RideJournal
    private var lastLivePost = Date.distantPast
    private var liveTask: Task<Void, Never>?
    /// Set by the app: posts JSON to /api/v1/live. Nil (e.g. in previews) skips live updates.
    var postLive: ((LiveUpdate) async -> Void)?

    static let livePostInterval: TimeInterval = 15

    init(journal: RideJournal = .standard) {
        self.journal = journal
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

    /// Start watching location for the map before a ride (foreground only).
    func warmUp() {
        if authorization == .notDetermined { feed.manager.requestWhenInUseAuthorization() }
        feed.start(background: false)
    }

    func coolDown() {
        if state == .idle { feed.stop() }
    }

    func start() {
        guard state == .idle else { return }
        if authorization == .notDetermined { feed.manager.requestWhenInUseAuthorization() }
        tracker = RideTracker()
        let now = Date()
        clock.start(at: now)
        journal.begin(start: now)
        state = .recording
        feed.start(background: true)
        sendLive(force: true)
    }

    func pause() {
        guard state == .recording else { return }
        state = .paused
        tracker.pause()
        clock.pause()
    }

    func resume() {
        guard state == .paused else { return }
        state = .recording
        tracker.resume()
        clock.resume()
        journal.newSegment()
    }

    /// Stops recording and returns the ride as GPX plus its summary. Throws, and keeps recording, if there's
    /// no usable track yet, so the user can carry on or discard rather than lose the ride.
    func finish() throws(AppError) -> (gpx: Data, summary: RideSummary) {
        guard state != .idle, let start = clock.startedAt else { throw .rideTooShort }
        guard tracker.pointCount >= 2 else { throw .rideTooShort }
        clock.pause()
        let gpx = GPXWriter.gpx(segments: tracker.segments, name: GPXWriter.rideName(start: start))
        let summary = RideSummary(start: start, tracker: tracker, elapsed: clock.elapsed())
        endRecording()
        return (gpx, summary)
    }

    func discard() {
        endRecording()
    }

    func takeRecovered() throws(AppError) -> (gpx: Data, summary: RideSummary) {
        guard let r = recovered else { throw .rideTooShort }
        recovered = nil
        journal.clear()
        let t = RideTracker(segments: r.segments)
        let end = t.lastPoint?.time ?? r.start
        return (GPXWriter.gpx(segments: r.segments, name: GPXWriter.rideName(start: r.start)),
                RideSummary(start: r.start, tracker: t, elapsed: end.timeIntervalSince(r.start)))
    }

    func discardRecovered() {
        recovered = nil
        journal.clear()
    }

    private func endRecording() {
        state = .idle
        journal.clear()
        feed.stop()
        sendLive(force: true)
    }

    private func received(_ locations: [CLLocation]) {
        guard let latest = locations.last else { return }
        lastLocation = latest
        guard state == .recording else { return }
        for location in locations where location.timestamp >= (clock.startedAt ?? .distantPast) {
            let point = RidePoint(location)
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
            state: state == .idle ? "idle" : "riding",
            lat: l?.coordinate.latitude, lng: l?.coordinate.longitude,
            speed_mps: state == .recording ? tracker.currentSpeed : 0,
            distance_m: tracker.distance, elapsed_s: Int(clock.elapsed()),
            alt_m: l.flatMap { $0.verticalAccuracy >= 0 ? $0.altitude : nil },
            accuracy_m: l?.horizontalAccuracy,
            sport: "Ride",
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
