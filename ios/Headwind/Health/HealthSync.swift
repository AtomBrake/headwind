import CoreLocation
import Foundation
import HealthKit
import Observation

/// What Headwind can read from Apple Health, each turned on by itself: HealthKit asks for each permission only when it's turned on, and the
/// user can refuse some and keep the rest. (HealthKit never says whether read access was granted; a refused type simply has no data.)
enum HealthMetric: String, CaseIterable, Identifiable, Codable, Sendable {
    case steps, restingHeartRate, hrv, sleep, weight, bodyFat, activeEnergy, restingEnergy, workouts

    var id: Self { self }

    var title: String {
        switch self {
        case .steps: "Steps"
        case .restingHeartRate: "Resting heart rate"
        case .hrv: "Heart rate variability"
        case .sleep: "Sleep"
        case .weight: "Weight"
        case .bodyFat: "Body fat"
        case .activeEnergy: "Active calories"
        case .restingEnergy: "Resting calories"
        case .workouts: "Workouts from other apps"
        }
    }

    var detail: String {
        switch self {
        case .steps: "The day's total, counted once across iPhone and Watch. Headwind takes the highest of every source."
        case .restingHeartRate: "For the recovery card and the AI coach."
        case .hrv: "Apple's is SDNN through the day, not Garmin's overnight figure, so it's kept apart from Garmin's."
        case .sleep: "Time asleep each night, dated to the morning it ends."
        case .weight: "Weigh-ins from a smart scale. A manual or Garmin entry for the same day is never replaced."
        case .bodyFat: "From a smart scale, on days with no other reading."
        case .activeEnergy: "With resting calories, the day's burn where there's no Garmin."
        case .restingEnergy: "With active calories, the day's burn where there's no Garmin."
        case .workouts: "Rides, runs, swims and sessions recorded by Apple's Workout app, Peloton and others, with their route and heart rate."
        }
    }

    var objectTypes: Set<HKObjectType> {
        switch self {
        case .steps: [HKQuantityType(.stepCount)]
        case .restingHeartRate: [HKQuantityType(.restingHeartRate)]
        case .hrv: [HKQuantityType(.heartRateVariabilitySDNN)]
        case .sleep: [HKCategoryType(.sleepAnalysis)]
        case .weight: [HKQuantityType(.bodyMass)]
        case .bodyFat: [HKQuantityType(.bodyFatPercentage)]
        case .activeEnergy: [HKQuantityType(.activeEnergyBurned)]
        case .restingEnergy: [HKQuantityType(.basalEnergyBurned)]
        case .workouts: [HKObjectType.workoutType(), HKSeriesType.workoutRoute(), HKQuantityType(.heartRate),
                         HKQuantityType(.distanceCycling), HKQuantityType(.distanceWalkingRunning), HKQuantityType(.distanceSwimming),
                         HKQuantityType(.activeEnergyBurned)]
        }
    }

    /// The type an observer query watches for new data.
    var sampleType: HKSampleType {
        switch self {
        case .steps: HKQuantityType(.stepCount)
        case .restingHeartRate: HKQuantityType(.restingHeartRate)
        case .hrv: HKQuantityType(.heartRateVariabilitySDNN)
        case .sleep: HKCategoryType(.sleepAnalysis)
        case .weight: HKQuantityType(.bodyMass)
        case .bodyFat: HKQuantityType(.bodyFatPercentage)
        case .activeEnergy: HKQuantityType(.activeEnergyBurned)
        case .restingEnergy: HKQuantityType(.basalEnergyBurned)
        case .workouts: HKObjectType.workoutType()
        }
    }
}

/// One day's figure for POST /api/v1/health/days (services/health.py METRICS).
struct HealthDay: Encodable, Equatable, Sendable {
    var date: String
    var metric: String
    var value: Double
}

/// Reads Apple Health on the iPhone and sends it to the server: daily steps, resting heart rate, HRV, sleep, weight, body fat and calories
/// (POST /api/v1/health/days, safe to send twice), and, if turned on, workouts recorded by other apps (uploaded as Headwind's own
/// recordings are, with an `ah_` client id so a second sync can't add one twice). Headwind's own workouts (the Watch saves every one to
/// Health) are left out.
///
/// Fresh data arrives through observer queries with background delivery (set up at launch, as HealthKit requires), plus a sync whenever the
/// app comes to the foreground. The first sync goes back `backfillDays`; later ones from two days before the last, to catch late Watch data.
@MainActor
@Observable
final class HealthSync {
    private(set) var enabled: Set<HealthMetric>
    private(set) var syncing = false
    private(set) var lastSync: Date?
    private(set) var lastError: String?
    /// Workouts from other apps sent so far, and the last pass's ones Headwind has no sport for (an elliptical, say).
    private(set) var workoutsSent: Int
    private(set) var workoutsSkipped = 0
    /// How far back the first sync goes. Going further back later sends the extra days (and looks at every workout again; the server
    /// keeps one copy of each).
    var backfillDays: Int {
        didSet {
            defaults.set(backfillDays, forKey: Keys.backfill)
            if backfillDays > oldValue {
                defaults.removeObject(forKey: Keys.through)
                defaults.removeObject(forKey: Keys.anchor)
            }
        }
    }

    static let backfillChoices = [30, 90, 365, 1095]
    static var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    @ObservationIgnored private let store = HKHealthStore()
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private var observers: [HealthMetric: HKObserverQuery] = [:]
    @ObservationIgnored private var syncAgain = false
    @ObservationIgnored private let calendar = Calendar.current

    private enum Keys {
        static let enabled = "health-enabled", backfill = "health-backfill", through = "health-synced-through",
                   lastSync = "health-last-sync", anchor = "health-workout-anchor", sent = "health-workouts-sent"
    }

    /// Batches for POST /health/days, well under the server's 5,000.
    static let batchSize = 2000
    /// Workouts fetched per anchored query, so a long backfill goes up a few at a time and resumes where it stopped.
    static let workoutBatch = 20
    /// Headwind's own apps: their workouts are already on the server.
    static let ownBundlePrefix = "io.github.atombrake.headwind"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        enabled = Set((defaults.stringArray(forKey: Keys.enabled) ?? []).compactMap(HealthMetric.init(rawValue:)))
        backfillDays = (defaults.object(forKey: Keys.backfill) as? Int) ?? 90
        lastSync = defaults.object(forKey: Keys.lastSync) as? Date
        workoutsSent = defaults.integer(forKey: Keys.sent)
    }

    /// Turn a metric on (asking HealthKit for it, then sending it) or off. Off stops sending; what the server has stays until "Remove".
    func set(_ metric: HealthMetric, on: Bool, using session: Session) async {
        guard Self.isAvailable else { return }
        if on {
            do {
                try await store.requestAuthorization(toShare: [], read: metric.objectTypes)
            } catch {
                lastError = error.localizedDescription
                return
            }
            enabled.insert(metric)
        } else {
            enabled.remove(metric)
        }
        defaults.set(enabled.map(\.rawValue), forKey: Keys.enabled)
        observe(using: session)
        if on { await sync(using: session) }
    }

    /// Forget everything sent from Apple Health, on the server (DELETE /api/v1/health) and here, and stop sending.
    func removeAll(using session: Session) async throws(AppError) {
        _ = try await session.call { client async throws(AppError) in try await client.delete("health", as: Ignored.self) }
        enabled = []
        for key in [Keys.enabled, Keys.through, Keys.lastSync, Keys.anchor, Keys.sent] { defaults.removeObject(forKey: key) }
        lastSync = nil
        workoutsSent = 0
        observe(using: session)
    }

    // MARK: - Keeping it fresh

    /// One observer query per metric that's on, with background delivery, so new data wakes the app. HealthKit needs these set up at
    /// every launch for background delivery to keep working.
    func observe(using session: Session) {
        guard Self.isAvailable else { return }
        for (metric, query) in observers where !enabled.contains(metric) {
            store.stop(query)
            observers[metric] = nil
            store.disableBackgroundDelivery(for: metric.sampleType) { _, _ in }
        }
        for metric in enabled where observers[metric] == nil {
            let query = HKObserverQuery(sampleType: metric.sampleType, predicate: nil) { [weak self] _, done, error in
                let finish = Completion(done)
                guard error == nil else { finish.call(); return }
                Task { @MainActor in
                    await self?.sync(using: session)
                    finish.call()       // tells HealthKit this update is dealt with, so it keeps waking the app
                }
            }
            observers[metric] = query
            store.execute(query)
            // Steps and calories change all day: hourly is plenty. The rest arrive once a day or at a weigh-in.
            store.enableBackgroundDelivery(for: metric.sampleType, frequency: [.steps, .activeEnergy, .restingEnergy].contains(metric) ? .hourly : .immediate) { _, _ in }
        }
    }

    /// Send what's new. Safe to call often: a call made mid-sync makes the running one go round again.
    func sync(using session: Session) async {
        guard Self.isAvailable, !enabled.isEmpty, session.pairing != nil else { return }
        guard !syncing else { syncAgain = true; return }
        syncing = true
        defer { syncing = false }
        repeat {
            syncAgain = false
            do throws(AppError) {
                try await syncDays(using: session)
                if enabled.contains(.workouts) { try await syncWorkouts(using: session) }
                lastSync = .now
                defaults.set(lastSync, forKey: Keys.lastSync)
                lastError = nil
            } catch {
                lastError = error.localizedDescription
                return
            }
        } while syncAgain
    }

    // MARK: - Daily figures

    private func syncDays(using session: Session) async throws(AppError) {
        let now = Date()
        let today = calendar.startOfDay(for: now)
        let first = calendar.date(byAdding: .day, value: -backfillDays, to: today) ?? today
        let through = (defaults.object(forKey: Keys.through) as? Date).flatMap { calendar.date(byAdding: .day, value: -2, to: $0) }
        let start = max(first, through ?? first)
        var days: [HealthDay] = []
        do {
            for metric in enabled {
                days += try await read(metric, from: start, to: now)
            }
        } catch {
            throw .health(underlying: error)
        }
        for batch in stride(from: 0, to: days.count, by: Self.batchSize).map({ Array(days[$0..<min($0 + Self.batchSize, days.count)]) }) {
            _ = try await session.call { client async throws(AppError) in
                try await client.post("health/days", json: ["days": batch], as: Ignored.self)
            }
        }
        defaults.set(today, forKey: Keys.through)
    }

    private func read(_ metric: HealthMetric, from start: Date, to end: Date) async throws -> [HealthDay] {
        let perMinute = HKUnit.count().unitDivided(by: .minute())
        switch metric {
        case .steps:
            return try await daily(.stepCount, .cumulativeSum, from: start, to: end, metric: "steps") { $0.sumQuantity()?.doubleValue(for: .count()) }
        case .activeEnergy:
            return try await daily(.activeEnergyBurned, .cumulativeSum, from: start, to: end, metric: "active_kcal") {
                $0.sumQuantity()?.doubleValue(for: .kilocalorie())
            }
        case .restingEnergy:
            return try await daily(.basalEnergyBurned, .cumulativeSum, from: start, to: end, metric: "basal_kcal") {
                $0.sumQuantity()?.doubleValue(for: .kilocalorie())
            }
        case .restingHeartRate:
            return try await daily(.restingHeartRate, .discreteAverage, from: start, to: end, metric: "resting_hr") {
                $0.averageQuantity()?.doubleValue(for: perMinute)
            }
        case .hrv:
            return try await daily(.heartRateVariabilitySDNN, .discreteAverage, from: start, to: end, metric: "hrv_sdnn") {
                $0.averageQuantity()?.doubleValue(for: .secondUnit(with: .milli))
            }
        case .weight:
            return try await daily(.bodyMass, .mostRecent, from: start, to: end, metric: "weight_kg") {
                $0.mostRecentQuantity()?.doubleValue(for: .gramUnit(with: .kilo))
            }
        case .bodyFat:
            return try await daily(.bodyFatPercentage, .mostRecent, from: start, to: end, metric: "body_fat") {
                $0.mostRecentQuantity().map { $0.doubleValue(for: .percent()) * 100 }
            }
        case .sleep:
            return try await sleep(from: start, to: end)
        case .workouts:
            return []
        }
    }

    /// One figure per local calendar day, from a statistics collection query: HealthKit merges iPhone, Watch and other apps' samples itself.
    private func daily(_ id: HKQuantityTypeIdentifier, _ options: HKStatisticsOptions, from start: Date, to end: Date, metric: String,
                       value: (HKStatistics) -> Double?) async throws -> [HealthDay] {
        let type = HKQuantityType(id)
        let query = HKStatisticsCollectionQueryDescriptor(
            predicate: .quantitySample(type: type, predicate: HKQuery.predicateForSamples(withStart: start, end: end)),
            options: options, anchorDate: calendar.startOfDay(for: start), intervalComponents: DateComponents(day: 1))
        let collection = try await query.result(for: store)
        // statistics() holds only the days with data.
        return collection.statistics().compactMap { stats in
            guard stats.startDate >= calendar.startOfDay(for: start), let v = value(stats), v > 0 else { return nil }
            return HealthDay(date: Self.day(stats.startDate, calendar), metric: metric, value: v)
        }
    }

    /// Hours asleep per night: every asleep stage from every source (Watch, iPhone, a sleep app), overlaps counted once, dated to the day the
    /// night ends, as Garmin's are.
    private func sleep(from start: Date, to end: Date) async throws -> [HealthDay] {
        // A night that ends on the first day began the evening before.
        let from = calendar.date(byAdding: .hour, value: -18, to: start) ?? start
        let query = HKSampleQueryDescriptor(
            predicates: [.categorySample(type: HKCategoryType(.sleepAnalysis), predicate: HKQuery.predicateForSamples(withStart: from, end: end))],
            sortDescriptors: [SortDescriptor(\.startDate)])
        let samples = try await query.result(for: store)
        let asleep = Set(HKCategoryValueSleepAnalysis.allAsleepValues.map(\.rawValue))
        let intervals = samples.filter { asleep.contains($0.value) }.map { ($0.startDate, $0.endDate) }
        return Self.nights(intervals, calendar: calendar)
            .filter { $0.date >= Self.day(start, calendar) }
    }

    /// Asleep intervals merged where they overlap, totalled per day of their end. Exposed for the tests.
    nonisolated static func nights(_ intervals: [(Date, Date)], calendar: Calendar) -> [HealthDay] {
        var byDay: [String: [(Date, Date)]] = [:]
        for (s, e) in intervals where e > s { byDay[day(e, calendar), default: []].append((s, e)) }
        return byDay.keys.sorted().compactMap { key in
            var total: TimeInterval = 0
            var current: (Date, Date)?
            for (s, e) in byDay[key]!.sorted(by: { $0.0 < $1.0 }) {
                if let c = current, s <= c.1 {
                    current = (c.0, max(c.1, e))
                } else {
                    if let c = current { total += c.1.timeIntervalSince(c.0) }
                    current = (s, e)
                }
            }
            if let c = current { total += c.1.timeIntervalSince(c.0) }
            let hours = (total / 3600 * 100).rounded() / 100
            return hours > 0 ? HealthDay(date: key, metric: "sleep_hours", value: min(hours, 24)) : nil
        }
    }

    nonisolated static func day(_ date: Date, _ calendar: Calendar) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    // MARK: - Workouts from other apps

    private func syncWorkouts(using session: Session) async throws(AppError) {
        let first = calendar.date(byAdding: .day, value: -backfillDays, to: calendar.startOfDay(for: .now)) ?? .now
        var anchor = (defaults.data(forKey: Keys.anchor)).flatMap { try? NSKeyedUnarchiver.unarchivedObject(ofClass: HKQueryAnchor.self, from: $0) }
        workoutsSkipped = 0
        while true {
            let query = HKAnchoredObjectQueryDescriptor(predicates: [.workout(HKQuery.predicateForSamples(withStart: first, end: nil))],
                                                        anchor: anchor, limit: Self.workoutBatch)
            let result: HKAnchoredObjectQueryDescriptor<HKWorkout>.Result
            do {
                result = try await query.result(for: store)
            } catch {
                throw .health(underlying: error)
            }
            for workout in result.addedSamples {
                try await send(workout, using: session)     // a failure stops here, before the anchor moves: the batch is read again next time
            }
            anchor = result.newAnchor
            if let data = try? NSKeyedArchiver.archivedData(withRootObject: result.newAnchor, requiringSecureCoding: true) {
                defaults.set(data, forKey: Keys.anchor)
            }
            // Deletions are left alone: the server's copy may be the one it kept of several (a Garmin ride), so deleting it would lose that.
            if result.addedSamples.count < Self.workoutBatch { break }
        }
    }

    private func send(_ workout: HKWorkout, using session: Session) async throws(AppError) {
        guard !workout.sourceRevision.source.bundleIdentifier.hasPrefix(Self.ownBundlePrefix), workout.duration >= RideSummary.minimumSession,
              let sport = Sport(health: workout.workoutActivityType, indoor: workout.metadata?[HKMetadataKeyIndoorWorkout] as? Bool ?? false)
        else {
            if !workout.sourceRevision.source.bundleIdentifier.hasPrefix(Self.ownBundlePrefix) { workoutsSkipped += 1 }
            return
        }
        let distance = sport.distanceType.flatMap { workout.statistics(for: $0)?.sumQuantity()?.doubleValue(for: .meter()) } ?? 0
        let kcal = workout.statistics(for: HKQuantityType(.activeEnergyBurned))?.sumQuantity()?.doubleValue(for: .kilocalorie())
        let points: [RidePoint]
        do {
            points = try await track(of: workout)
        } catch {
            throw .health(underlying: error)
        }
        let hrs = points.compactMap(\.hr)
        // Without a route it goes up timed, as the sport it is (a run with the phone left at home is still a run).
        let summary = RideSummary(start: workout.startDate, distance: distance, movingTime: workout.duration, elapsedTime: workout.duration,
                                  elevationGain: 0, averageHeartRate: hrs.isEmpty ? nil : hrs.reduce(0, +) / hrs.count, sport: sport, calories: kcal)
        let name = GPXWriter.rideName(summary)
        let gpx = points.count >= 2 ? GPXWriter.gpx(segments: [points], name: name, type: sport.gpxType, creator: "Apple Health") : nil
        do throws(AppError) {
            _ = try await session.call { client async throws(AppError) in
                try await Uploader.upload(summary: summary, id: workout.uuid, name: name, gpx: gpx, clientID: Self.clientID(workout.uuid),
                                          with: client)
            }
            workoutsSent += 1
            defaults.set(workoutsSent, forKey: Keys.sent)
        } catch {
            guard error.isRejection else { throw error }     // one the server can't read is skipped, not retried for ever
        }
    }

    /// The same id for a workout every time it's sent: `ah_` and its HealthKit UUID, as the Apple Health export import names them, so a
    /// workout that came in from an export isn't saved again.
    nonisolated static func clientID(_ uuid: UUID) -> String { "ah_" + uuid.uuidString.lowercased() }

    /// The workout's route with the heart rate nearest each point, or nothing for one without a route.
    private func track(of workout: HKWorkout) async throws -> [RidePoint] {
        let routes = try await HKSampleQueryDescriptor(
            predicates: [.sample(type: HKSeriesType.workoutRoute(), predicate: HKQuery.predicateForObjects(from: workout))],
            sortDescriptors: [SortDescriptor(\.startDate)]).result(for: store)
        var locations: [CLLocationSnapshot] = []
        for case let route as HKWorkoutRoute in routes {
            locations += try await Self.locations(of: route, in: store)
        }
        guard locations.count >= 2 else { return [] }
        let hr = try await HKSampleQueryDescriptor(
            predicates: [.quantitySample(type: HKQuantityType(.heartRate),
                                         predicate: HKQuery.predicateForSamples(withStart: workout.startDate, end: workout.endDate))],
            sortDescriptors: [SortDescriptor(\.startDate)]).result(for: store)
        let perMinute = HKUnit.count().unitDivided(by: .minute())
        let beats = hr.map { ($0.startDate, Int($0.quantity.doubleValue(for: perMinute).rounded())) }
        var i = 0
        return locations.sorted { $0.time < $1.time }.map { loc in
            while i + 1 < beats.count, beats[i + 1].0 <= loc.time { i += 1 }
            let near = beats.isEmpty ? nil : (abs(beats[i].0.timeIntervalSince(loc.time)) < 60 ? beats[i].1 : nil)
            return RidePoint(time: loc.time, lat: loc.lat, lon: loc.lon, ele: loc.ele, accuracy: loc.accuracy, speed: loc.speed, hr: near)
        }
    }

    /// A route's locations, which HealthKit hands over in batches through a callback.
    nonisolated private static func locations(of route: HKWorkoutRoute, in store: HKHealthStore) async throws -> [CLLocationSnapshot] {
        try await withCheckedThrowingContinuation { continuation in
            let collected = LocationBox()
            let query = HKWorkoutRouteQuery(route: route) { _, batch, done, error in
                if let error {
                    continuation.resume(throwing: error)
                    return
                }
                collected.append(batch ?? [])
                if done { continuation.resume(returning: collected.items) }
            }
            store.execute(query)
        }
    }
}

/// What's kept of a route point: plain values, so they cross from HealthKit's queue.
struct CLLocationSnapshot: Sendable {
    var time: Date
    var lat: Double
    var lon: Double
    var ele: Double?
    var accuracy: Double?
    var speed: Double?
}

/// Collects a route query's batches; HealthKit calls the handler serially on its own queue.
private final class LocationBox: @unchecked Sendable {
    private(set) var items: [CLLocationSnapshot] = []
    func append(_ batch: [CLLocation]) {
        items += batch.map {
            CLLocationSnapshot(time: $0.timestamp, lat: $0.coordinate.latitude, lon: $0.coordinate.longitude,
                               ele: $0.verticalAccuracy >= 0 ? $0.altitude : nil, accuracy: $0.horizontalAccuracy,
                               speed: $0.speed >= 0 ? $0.speed : nil)
        }
    }
}

/// HealthKit's completion handler, carried into the main actor. It's safe to call from anywhere.
private struct Completion: @unchecked Sendable {
    let call: () -> Void
    init(_ call: @escaping () -> Void) { self.call = call }
}

extension Sport {
    /// The sport Headwind records a HealthKit workout as, or nil for one it has none for (an elliptical, a dance class).
    init?(health type: HKWorkoutActivityType, indoor: Bool) {
        switch type {
        case .cycling: self = indoor ? .indoorRide : .ride
        case .running: self = indoor ? .treadmill : .run
        case .walking: self = .walk
        case .hiking: self = .hike
        case .swimming: self = indoor ? .poolSwim : .openWaterSwim
        case .traditionalStrengthTraining, .functionalStrengthTraining, .coreTraining, .crossTraining: self = .strength
        case .highIntensityIntervalTraining: self = .hiit
        case .yoga: self = .yoga
        default: return nil
        }
    }
}
