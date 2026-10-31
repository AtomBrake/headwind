import CoreLocation
import Foundation
import HealthKit
import Observation
import WatchKit

/// Records any sport on the Watch. A HealthKit workout session of the matching type keeps the app running with the wrist down and supplies
/// heart rate, calories and (from sensors paired with the Watch) power and cadence; Core Location supplies the track for the GPS sports.
/// When it ends it's saved to Apple Health (with its route) and handed to the iPhone, as GPX with heart rate on every point, or for a
/// timed-only session (strength, an indoor ride, a pool swim) as its summary: time, HealthKit's distance, calories and average heart rate.
///
/// One instance, `shared`, so the Action button's intents (WorkoutIntents.swift) drive the same recording the screens show.
@MainActor
@Observable
final class WorkoutManager: NSObject {
    enum State: Equatable { case idle, starting, recording, paused, saving, finished }

    static let shared = WorkoutManager(phone: PhoneLink())

    private(set) var state: State = .idle
    private(set) var tracker = RideTracker()
    private(set) var clock = ActiveClock()
    private(set) var heartRate: Int?
    private(set) var averageHeartRate: Int?
    private(set) var activeEnergy: Double = 0
    /// Watts and rpm, latest, from a power meter or cadence sensor paired with the Watch.
    private(set) var power: Int?
    private(set) var cadence: Int?
    /// HealthKit's distance for the sport: what a timed-only session reports (lengths swum, a treadmill's steps), since it has no track.
    private(set) var healthDistance: Double = 0
    private(set) var lastSummary: RideSummary?
    /// Whether the last finished ride was handed to the phone link, for the summary's "Sent to iPhone".
    private(set) var lastSent = false
    private(set) var error: AppError?
    /// A ride left in the journal by a crash, waiting to be saved or discarded.
    private(set) var recovered: RideJournal.Recovered?
    /// The sport for the next recording, or the one recording now. Chosen before Start, remembered for next time.
    private(set) var sport: Sport
    /// The bike last chosen in the picker; see Bike.pick.
    private(set) var chosenBike: Int?
    /// The bike the recording in progress is on.
    private(set) var bikeId: Int?
    /// The pool's length for a pool swim, in metres.
    private(set) var poolLength: Double

    private let healthStore = HKHealthStore()
    private var session: HKWorkoutSession?
    private var builder: HKLiveWorkoutBuilder?
    private var routeBuilder: HKWorkoutRouteBuilder?
    private let location = CLLocationManager()
    private let journal = RideJournal.standard
    private let choices = RecordChoices()
    private var noteTask: Task<Void, Never>?
    let phone: PhoneLink

    init(phone: PhoneLink) {
        self.phone = phone
        sport = choices.sport
        chosenBike = choices.bikeId
        poolLength = choices.poolLength
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
                                       HKQuantityType(.distanceCycling), HKQuantityType(.distanceWalkingRunning),
                                       HKQuantityType(.distanceSwimming), HKQuantityType(.cyclingPower), HKQuantityType(.cyclingCadence),
                                       HKQuantityType(.cyclingSpeed)]
        try? await healthStore.requestAuthorization(toShare: share, read: read)
        if sport.usesGPS, location.authorizationStatus == .notDetermined { location.requestWhenInUseAuthorization() }
    }

    /// Locked once recording: a ride can't become a run halfway.
    func choose(sport: Sport) {
        guard !isActive, state != .saving else { return }
        self.sport = sport
        choices.sport = sport
    }

    func choose(bike: Int?) {
        guard !isActive, state != .saving else { return }
        chosenBike = bike
        choices.bikeId = bike
    }

    func choose(poolLength: Double) {
        guard !isActive, state != .saving, poolLength >= 10, poolLength <= 100 else { return }
        self.poolLength = poolLength
        choices.poolLength = poolLength
    }

    /// The bike a ride starts on: the picker's choice if it's still the rider's, else the server's default.
    var bikeToRide: Int? { Bike.pick(chosenBike, from: phone.bikes) }

    /// `bike` is the one to ride on (Bike.pick of the picker's choice); ignored on foot.
    func start(bike: Int? = nil) async {
        guard state == .idle || state == .finished else { return }
        error = nil
        lastSent = false
        // Starting replaces the journal, so send an unfinished ride first; if that fails, don't start.
        if recovered != nil {
            saveRecovered()
            guard recovered == nil else { return }
            error = nil   // one too short to keep was dropped: nothing to report as the new ride starts
        }
        state = .starting
        await requestAuthorization()

        let config = configuration(for: sport)
        var started: HKWorkoutSession?
        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: config)
            started = session
            let builder = session.associatedWorkoutBuilder()
            builder.dataSource = HKLiveWorkoutDataSource(healthStore: healthStore, workoutConfiguration: config)
            session.delegate = self
            builder.delegate = self
            self.session = session
            self.builder = builder
            routeBuilder = sport.usesGPS ? HKWorkoutRouteBuilder(healthStore: healthStore, device: nil) : nil

            let now = Date()
            tracker = RideTracker()
            bikeId = sport.isRide ? bike : nil
            clock.start(at: now)
            heartRate = nil
            averageHeartRate = nil
            power = nil
            cadence = nil
            activeEnergy = 0
            healthDistance = 0
            journal.begin(start: now, sport: sport, bikeId: bikeId)
            session.startActivity(with: now)
            try await builder.beginCollection(at: now)
            // The session can fail or end while collection starts, and has then already been cleaned up or finished.
            guard self.session === session, state == .starting else { return }
            if sport.usesGPS { location.startUpdatingLocation() }
            if sport.isSwim { WKInterfaceDevice.current().enableWaterLock() }
            if !sport.usesGPS { startNotes() }
            state = .recording
            await ActionButton.donateNextAction()
        } catch {
            guard self.session === started else { return }
            self.error = .health(underlying: error)
            // startActivity has already run, so end the session or it keeps the app running as a workout.
            self.session?.end()
            reset()
        }
    }

    /// What Apple Health records it as, where, and for a pool swim the pool's length so the Watch can count lengths.
    private func configuration(for sport: Sport) -> HKWorkoutConfiguration {
        let config = HKWorkoutConfiguration()
        config.activityType = sport.workoutType
        config.locationType = sport.usesGPS ? .outdoor : .indoor
        switch sport {
        case .poolSwim:
            config.swimmingLocationType = .pool
            config.lapLength = HKQuantity(unit: .meter(), doubleValue: poolLength)
        case .openWaterSwim:
            config.swimmingLocationType = .openWater
        default:
            break
        }
        return config
    }

    func pause() {
        guard state == .recording else { return }
        session?.pause()
    }

    func resume() {
        guard state == .paused else { return }
        session?.resume()
    }

    func togglePause() {
        state == .paused ? resume() : pause()
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

    /// Keeps the recovered ride, journal and all, if it can't be handed to the phone. One with too little to save, as
    /// finishWorkout would refuse, is discarded.
    func saveRecovered() {
        guard let r = recovered else { return }
        if r.session == nil, RideTracker(segments: r.segments).pointCount < 2 {
            discardRecovered()
            error = .rideTooShort
            return
        }
        let summary = RideJournal.summary(of: r)
        do throws(AppError) {
            if r.session == nil {
                try send(segments: r.segments, summary: summary)
            } else {
                try phone.send(session: summary)
            }
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

    /// Runs once per ride, from whichever comes first: HealthKit confirming `end()`, the system ending the
    /// session itself, or the session failing.
    private func finishWorkout(at end: Date) async {
        guard let builder, let start = clock.startedAt else { return }
        self.builder = nil   // claims the finish, so a later .ended or failure for this session does nothing
        let routeBuilder = self.routeBuilder
        state = .saving
        clock.pause(at: end)
        noteTask?.cancel()
        noteTask = nil
        location.stopUpdatingLocation()
        let elapsed = clock.elapsed(at: end)
        let kcal = activeEnergy > 0 ? activeEnergy : nil
        let summary = sport.usesGPS
            ? RideSummary(start: start, tracker: tracker, elapsed: elapsed, sport: sport, bikeId: bikeId, calories: kcal)
            : .session(start: start, elapsed: elapsed, sport: sport, distance: healthDistance, averageHeartRate: averageHeartRate,
                       calories: kcal, bikeId: bikeId)
        do {
            try await builder.endCollection(at: end)
            if let workout = try await builder.finishWorkout(), tracker.pointCount >= 2 {
                _ = try? await routeBuilder?.finishRoute(with: workout, metadata: nil)
            }
        } catch {
            // Health couldn't save it; the ride still goes to Headwind. A session failure's error is kept.
            self.error = self.error ?? .health(underlying: error)
        }
        let keep = sport.usesGPS ? tracker.pointCount >= 2 : elapsed >= RideSummary.minimumSession
        if keep {
            do throws(AppError) {
                if sport.usesGPS {
                    try send(segments: tracker.segments, summary: summary)
                } else {
                    try phone.send(session: summary)
                }
                lastSent = true
                journal.clear()
            } catch {
                // Couldn't queue it for the phone (e.g. Watch storage full): keep the journal and offer it again.
                self.error = error
                recovered = journal.load()
            }
        } else {
            error = error ?? (sport.usesGPS ? .rideTooShort : .sessionTooShort)
            journal.clear()
        }
        lastSummary = summary
        session = nil
        self.routeBuilder = nil
        state = .finished
    }

    private func send(segments: [[RidePoint]], summary: RideSummary) throws(AppError) {
        let gpx = GPXWriter.gpx(segments: segments, summary: summary, creator: "Headwind watchOS")
        try phone.send(gpx: gpx, summary: summary)
    }

    private func reset() {
        location.stopUpdatingLocation()
        noteTask?.cancel()
        noteTask = nil
        session = nil
        builder = nil
        routeBuilder = nil
        state = .idle
        journal.clear()
    }

    /// A timed-only session has no fixes to journal, so its progress is noted every 30 s instead.
    private func startNotes() {
        noteTask?.cancel()
        noteTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                self?.noteSession()
            }
        }
    }

    private func noteSession() {
        guard isActive, !sport.usesGPS else { return }
        journal.note(.init(at: .now, active: clock.elapsed(), distance: healthDistance > 0 ? healthDistance : nil,
                           calories: activeEnergy > 0 ? activeEnergy : nil, heartRate: averageHeartRate))
    }

    // MARK: - Events (hopped onto the main actor by the delegate methods below)

    private func sessionChanged(_ changed: HKWorkoutSession, to newState: HKWorkoutSessionState, at date: Date) {
        guard changed === session else { return }   // a session already ended or abandoned
        switch newState {
        case .running where state == .paused:
            state = .recording
            tracker.resume()
            clock.resume(at: date)
            if sport.usesGPS { journal.newSegment() }
        case .paused where state == .recording:
            state = .paused
            tracker.pause()
            clock.pause(at: date)
            noteSession()
        case .ended:
            Task { await finishWorkout(at: date) }
        default:
            break
        }
    }

    /// A failed session may never reach .ended, so end it and finish the ride here rather than wait.
    private func sessionFailed(_ failed: HKWorkoutSession, error: Error) {
        guard failed === session else { return }
        self.error = .health(underlying: error)
        failed.end()
        switch state {
        case .starting:
            reset()   // start() sees the session is gone and stops there
        case .recording, .paused, .saving:
            Task { await finishWorkout(at: Date()) }
        default:
            break
        }
    }

    private func received(_ locations: [CLLocation]) {
        guard state == .recording, sport.usesGPS else { return }
        let fresh = locations.filter { $0.timestamp >= (clock.startedAt ?? .distantPast) }
        var kept: [CLLocation] = []
        for loc in fresh {
            let point = RidePoint(loc, hr: heartRate, power: power, cadence: cadence)
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
        let perMinute = HKUnit.count().unitDivided(by: .minute())
        if let hr = statistics[HKQuantityType(.heartRate)] {
            if let latest = hr.mostRecentQuantity() { heartRate = Int(latest.doubleValue(for: perMinute).rounded()) }
            if let avg = hr.averageQuantity() { averageHeartRate = Int(avg.doubleValue(for: perMinute).rounded()) }
        }
        if let energy = statistics[HKQuantityType(.activeEnergyBurned)]?.sumQuantity() {
            activeEnergy = energy.doubleValue(for: .kilocalorie())
        }
        if let watts = statistics[HKQuantityType(.cyclingPower)]?.mostRecentQuantity() {
            power = Int(watts.doubleValue(for: .watt()).rounded())
        }
        if let rpm = statistics[HKQuantityType(.cyclingCadence)]?.mostRecentQuantity() {
            cadence = Int(rpm.doubleValue(for: perMinute).rounded())
        }
        if let type = sport.distanceType, let d = statistics[type]?.sumQuantity() {
            healthDistance = d.doubleValue(for: .meter())
        }
    }
}

extension WorkoutManager: HKWorkoutSessionDelegate {
    nonisolated func workoutSession(_ workoutSession: HKWorkoutSession, didChangeTo toState: HKWorkoutSessionState,
                                    from fromState: HKWorkoutSessionState, date: Date) {
        Task { @MainActor in self.sessionChanged(workoutSession, to: toState, at: date) }
    }

    nonisolated func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        Task { @MainActor in self.sessionFailed(workoutSession, error: error) }
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
