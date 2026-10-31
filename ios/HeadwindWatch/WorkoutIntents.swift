import AppIntents
import Foundation

// The Action button on Apple Watch Ultra (Settings > Action Button > Workout > Headwind). The first press starts the workout chosen under
// First Press; pressing it again during the workout pauses or resumes (the "next action" donated once recording starts); pressing it with
// the side button pauses and resumes too, as in Apple's Workout app. They live in the Watch app itself, not an extension, as Apple requires,
// and run on the one WorkoutManager the screens show.
//
// The system launches the app before perform() and allows 30 s to start the workout session. Starting needs HealthKit permission, which
// the app asks for the first time it starts a workout; until then the system just opens the app on a press.

/// The workouts the Action button can start: every sport the Watch records. The display strings are literals because the build reads
/// them into the app's intent metadata, which is what Settings > Action Button shows.
enum HeadwindWorkoutStyle: String, AppEnum, CaseIterable {
    case ride, ebike, run, walk, hike, indoorRide, treadmill, poolSwim, openWaterSwim, strength, hiit, yoga

    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Workout"

    static let caseDisplayRepresentations: [HeadwindWorkoutStyle: DisplayRepresentation] = [
        .ride: DisplayRepresentation(title: "Ride", subtitle: "Outdoor, with GPS", image: .init(systemName: "bicycle")),
        .ebike: DisplayRepresentation(title: "E-bike ride", subtitle: "Outdoor, with GPS", image: .init(systemName: "bolt.fill")),
        .run: DisplayRepresentation(title: "Run", subtitle: "Outdoor, with GPS", image: .init(systemName: "figure.run")),
        .walk: DisplayRepresentation(title: "Walk", subtitle: "Outdoor, with GPS", image: .init(systemName: "figure.walk")),
        .hike: DisplayRepresentation(title: "Hike", subtitle: "Outdoor, with GPS", image: .init(systemName: "figure.hiking")),
        .indoorRide: DisplayRepresentation(title: "Indoor ride", subtitle: "Timed, with heart rate", image: .init(systemName: "figure.indoor.cycle")),
        .treadmill: DisplayRepresentation(title: "Treadmill run", subtitle: "Timed, with heart rate", image: .init(systemName: "figure.run.circle")),
        .poolSwim: DisplayRepresentation(title: "Pool swim", subtitle: "Lengths, with water lock", image: .init(systemName: "figure.pool.swim")),
        .openWaterSwim: DisplayRepresentation(title: "Open water swim", subtitle: "With GPS and water lock",
                                              image: .init(systemName: "figure.open.water.swim")),
        .strength: DisplayRepresentation(title: "Strength", subtitle: "Timed, with heart rate",
                                         image: .init(systemName: "figure.strengthtraining.traditional")),
        .hiit: DisplayRepresentation(title: "HIIT", subtitle: "Timed, with heart rate",
                                     image: .init(systemName: "figure.highintensity.intervaltraining")),
        .yoga: DisplayRepresentation(title: "Yoga", subtitle: "Timed, with heart rate", image: .init(systemName: "figure.yoga")),
    ]

    var sport: Sport {
        switch self {
        case .ride: .ride
        case .ebike: .ebike
        case .run: .run
        case .walk: .walk
        case .hike: .hike
        case .indoorRide: .indoorRide
        case .treadmill: .treadmill
        case .poolSwim: .poolSwim
        case .openWaterSwim: .openWaterSwim
        case .strength: .strength
        case .hiit: .hiit
        case .yoga: .yoga
        }
    }

    init(_ sport: Sport) {
        self = Self.allCases.first { $0.sport == sport } ?? .ride
    }
}

/// First press: start the chosen workout.
struct StartHeadwindWorkoutIntent: StartWorkoutIntent {
    static let title: LocalizedStringResource = "Start Headwind Workout"

    /// The choices under First Press. The last sport chosen on the Watch comes first.
    static var suggestedWorkouts: [StartHeadwindWorkoutIntent] {
        let last = HeadwindWorkoutStyle(RecordChoices().sport)
        return ([last] + HeadwindWorkoutStyle.allCases.filter { $0 != last }).map { StartHeadwindWorkoutIntent(style: $0) }
    }

    @Parameter(title: "Workout")
    var workoutStyle: HeadwindWorkoutStyle

    init() {
        workoutStyle = .ride
    }

    init(style: HeadwindWorkoutStyle) {
        workoutStyle = style
    }

    var displayRepresentation: DisplayRepresentation {
        HeadwindWorkoutStyle.caseDisplayRepresentations[workoutStyle] ?? DisplayRepresentation(title: "Workout")
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        let workout = WorkoutManager.shared
        guard !workout.isActive, workout.state != .saving else { return .result() }   // already recording: a second press is the next action
        if workout.state == .finished { workout.dismissSummary() }
        workout.choose(sport: workoutStyle.sport)
        await workout.start(bike: workout.bikeToRide)
        return .result()
    }
}

/// A press during the workout: pause, or resume if paused. Donated as the next action once recording starts.
struct ToggleHeadwindPauseIntent: AppIntent {
    static let title: LocalizedStringResource = "Pause or Resume"
    static let isDiscoverable = false

    @MainActor
    func perform() async throws -> some IntentResult {
        WorkoutManager.shared.togglePause()
        return .result()
    }
}

/// Action button and side button together while recording.
struct PauseHeadwindWorkoutIntent: PauseWorkoutIntent {
    static let title: LocalizedStringResource = "Pause Workout"

    @MainActor
    func perform() async throws -> some IntentResult {
        WorkoutManager.shared.pause()
        return .result()
    }
}

/// Action button and side button together while paused.
struct ResumeHeadwindWorkoutIntent: ResumeWorkoutIntent {
    static let title: LocalizedStringResource = "Resume Workout"

    @MainActor
    func perform() async throws -> some IntentResult {
        WorkoutManager.shared.resume()
        return .result()
    }
}

enum ActionButton {
    /// Make pause/resume the Action button's next action for the workout that just started, however it was started (the button or the
    /// screen). Best effort: on a Watch without an Action button the donation does nothing.
    @MainActor
    static func donateNextAction() async {
        _ = try? await StartHeadwindWorkoutIntent().donate(result: .result(actionButtonIntent: ToggleHeadwindPauseIntent()))
    }
}
