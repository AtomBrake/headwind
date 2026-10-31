import HealthKit

extension Sport {
    /// What Apple Health records it as. There's no e-bike type: an e-bike ride is cycling.
    var workoutType: HKWorkoutActivityType {
        switch self {
        case .ride, .ebike, .indoorRide: .cycling
        case .run, .treadmill: .running
        case .walk: .walking
        case .hike: .hiking
        case .poolSwim, .openWaterSwim: .swimming
        case .strength: .traditionalStrengthTraining
        case .hiit: .highIntensityIntervalTraining
        case .yoga: .yoga
        }
    }

    /// The HealthKit distance the sport measures: what the Watch counts in a timed session (lengths swum, a treadmill's steps), and what
    /// a workout from another app carries.
    var distanceType: HKQuantityType? {
        switch self {
        case .ride, .ebike, .indoorRide: HKQuantityType(.distanceCycling)
        case .run, .walk, .hike, .treadmill: HKQuantityType(.distanceWalkingRunning)
        case .poolSwim, .openWaterSwim: HKQuantityType(.distanceSwimming)
        case .strength, .hiit, .yoga: nil
        }
    }
}
