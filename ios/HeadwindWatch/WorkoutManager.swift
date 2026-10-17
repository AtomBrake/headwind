import CoreLocation
import Foundation
import HealthKit
import Observation

/// Records a ride on the Watch. A HealthKit cycling workout session keeps the app running with the wrist down
/// and supplies heart rate; Core Location supplies the track. When the ride ends it's saved to Apple Health
/// (with its route) and handed to the iPhone as GPX, heart rate on every point, for upload to Headwind.
@MainActor
@Observable
final class WorkoutManager: NSObject {
    enum State: Equatable { case idle, starting, recording, paused, saving, finished }

    private(set) var state: State = .idle
    private(set) var tracker = RideTracker()
    private(set) var clock = ActiveClock()
    private(set) var heartRate: Int?
    private(set) var activeEnergy: Double = 0
    private(set) var lastSummary: RideSummary?
    private(set) var error: AppError?
    /// A ride left in the journal by a crash, waiting to be saved or discarded.
    private(set) var recovered: (start: Date, segments: [[RidePoint]])?

    private let healthStore = HKHealthStore()
    private var session: HKWorkoutSession?
    private var builder: HKLiveWorkoutBuilder?
    private var routeBuilder: HKWorkoutRouteBuilder?
    private let location = CLLocationManager()
    private let journal = RideJournal.standard
    let phone: PhoneLink

    init(phone: PhoneLink) {
        self.phone = phone
        super.init()
        location.delegate = self
        location.desiredAccuracy = kCLLocationAccuracyBest
        location.distanceFilter = kCLDistanceFilterNone
        location.activityType = .fitness
        recovered = journal.load()
    }

    var isActive: Bool { [.starting, .recording, .paused].contains(state) }

    func requestAuthorization() async {
        let share: Set<HKSampleType> = [HKQuantityType.workoutType(), HKSeriesType.workoutRoute()]
        let read: Set<HKObjectType> = [HKQuantityType(.heartRate), HKQuantityType(.activeEnergyBurned),
                                       HKQuantityType(.distanceCycling)]
        try? await healthStore.requestAuthorization(toShare: share, read: read)
        if location.authorizationStatus == .notDetermined { location.requestWhenInUseAuthorization() }
    }

    func start() async {
        guard state == .idle || state == .finished else { return }
        error = nil
        // Starting replaces the journal, so send an unfinished ride first; if that fails, don't start.
        if recovered != nil {
            saveRecovered()
            guard recovered == nil else { return }
        }
        state = .starting
        await requestAuthorization()

        let config = HKWorkoutConfiguration()
        config.activityType = .cycling
        config.locationType = .outdoor
        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: config)
            let builder = session.associatedWorkoutBuilder()
            builder.dataSource = HKLiveWorkoutDataSource(healthStore: healthStore, workoutConfiguration: config)
            session.delegate = self
            builder.delegate = self
            self.session = session
            self.builder = builder
            routeBuilder = HKWorkoutRouteBuilder(healthStore: healthStore, device: nil)

            let now = Date()
            tracker = RideTracker()
            clock.start(at: now)
            heartRate = nil
            activeEnergy = 0
            journal.begin(start: now)
            session.startActivity(with: now)
            try await builder.beginCollection(at: now)
            location.startUpdatingLocation()
            state = .recording
        } catch {
            self.error = .health(underlying: error)
            reset()
        }
    }

    func pause() {
        guard state == .recording else { return }
        session?.pause()
    }

    func resume() {
        guard state == .paused else { return }
        session?.resume()
    }

    func end() {
        guard isActive else { return }
        state = .saving
        clock.pause()
        location.stopUpdatingLocation()
        session?.end()   // finishing continues in workoutSession(_:didChangeTo:) once HealthKit confirms
    }

    func dismissSummary() {
        state = .idle
        lastSummary = nil
    }

    /// Keeps the recovered ride, journal and all, if it can't be handed to the phone.
    func saveRecovered() {
        guard let r = recovered else { return }
        let t = RideTracker(segments: r.segments)
        let end = t.lastPoint?.time ?? r.start
        do throws(AppError) {
            try send(segments: r.segments, summary: RideSummary(start: r.start, tracker: t, elapsed: end.timeIntervalSince(r.start)))
            recovered = nil
            journal.clear()
        } catch {
            self.error = error
        }
    }

    func discardRecovered() {
        recovered = nil
        journal.clear()
    }

    // MARK: - Finishing

    private func finishWorkout(at end: Date) async {
        guard let builder, let start = clock.startedAt else { reset(); return }
        let summary = RideSummary(start: start, tracker: tracker, elapsed: clock.elapsed(at: end))
        do {
            try await builder.endCollection(at: end)
            if let workout = try await builder.finishWorkout(), tracker.pointCount >= 2 {
                _ = try? await routeBuilder?.finishRoute(with: workout, metadata: nil)
            }
        } catch {
            // Health couldn't save it; the ride still goes to Headwind.
            self.error = .health(underlying: error)
        }
        if tracker.pointCount >= 2 {
            do throws(AppError) {
                try send(segments: tracker.segments, summary: summary)
                journal.clear()
            } catch {
                // Couldn't queue it for the phone (e.g. Watch storage full): keep the journal and offer it again.
                self.error = error
                recovered = journal.load()
            }
        } else {
            error = error ?? .rideTooShort
            journal.clear()
        }
        lastSummary = summary
        session = nil
        self.builder = nil
        routeBuilder = nil
        state = .finished
    }

    private func send(segments: [[RidePoint]], summary: RideSummary) throws(AppError) {
        let gpx = GPXWriter.gpx(segments: segments, name: GPXWriter.rideName(start: summary.start), creator: "Headwind watchOS")
        try phone.send(gpx: gpx, summary: summary)
    }

    private func reset() {
        location.stopUpdatingLocation()
        session = nil
        builder = nil
        routeBuilder = nil
        state = .idle
        journal.clear()
    }

    // MARK: - Events (hopped onto the main actor by the delegate methods below)

    private func sessionChanged(to newState: HKWorkoutSessionState, at date: Date) {
        switch newState {
        case .running where state == .paused:
            state = .recording
            tracker.resume()
            clock.resume(at: date)
            journal.newSegment()
        case .paused where state == .recording:
            state = .paused
            tracker.pause()
            clock.pause(at: date)
        case .ended:
            Task { await finishWorkout(at: date) }
        default:
            break
        }
    }

    private func received(_ locations: [CLLocation]) {
        guard state == .recording else { return }
        let fresh = locations.filter { $0.timestamp >= (clock.startedAt ?? .distantPast) }
        var kept: [CLLocation] = []
        for loc in fresh {
            let point = RidePoint(loc, hr: heartRate)
            if tracker.add(point) {
                journal.append(point)
                kept.append(loc)
            }
        }
        if !kept.isEmpty, let routeBuilder {
            // Best effort: the GPX for Headwind already has these points; only the Health map would miss them.
            Task { try? await routeBuilder.insertRouteData(kept) }
        }
    }

    private func collected(_ statistics: [HKQuantityType: HKStatistics]) {
        if let hr = statistics[HKQuantityType(.heartRate)]?.mostRecentQuantity() {
            heartRate = Int(hr.doubleValue(for: HKUnit.count().unitDivided(by: .minute())).rounded())
        }
        if let energy = statistics[HKQuantityType(.activeEnergyBurned)]?.sumQuantity() {
            activeEnergy = energy.doubleValue(for: .kilocalorie())
        }
    }
}

extension WorkoutManager: HKWorkoutSessionDelegate {
    nonisolated func workoutSession(_ workoutSession: HKWorkoutSession, didChangeTo toState: HKWorkoutSessionState,
                                    from fromState: HKWorkoutSessionState, date: Date) {
        Task { @MainActor in self.sessionChanged(to: toState, at: date) }
    }

    nonisolated func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        Task { @MainActor in self.error = .health(underlying: error) }
    }
}

extension WorkoutManager: HKLiveWorkoutBuilderDelegate {
    nonisolated func workoutBuilderDidCollectEvent(_ workoutBuilder: HKLiveWorkoutBuilder) {}

    nonisolated func workoutBuilder(_ workoutBuilder: HKLiveWorkoutBuilder, didCollectDataOf collectedTypes: Set<HKSampleType>) {
        var stats: [HKQuantityType: HKStatistics] = [:]
        for case let type as HKQuantityType in collectedTypes {
            if let s = workoutBuilder.statistics(for: type) { stats[type] = s }
        }
        Task { @MainActor in self.collected(stats) }
    }
}

extension WorkoutManager: CLLocationManagerDelegate {
    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        Task { @MainActor in self.received(locations) }
    }
}
