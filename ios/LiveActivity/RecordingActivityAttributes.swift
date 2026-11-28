#if canImport(ActivityKit)
import ActivityKit
import Foundation

/// The recording in progress as a Live Activity (ActivityKit): its figures on the Lock Screen and in the Dynamic Island, and whether its
/// live tracking link is being shared. Compiled into the app, which starts and updates it (RecordingActivityController), and into the
/// HeadwindWidgets extension, which draws it (RecordingLiveActivity). Everything shown comes formatted from the app, in the server's
/// units, so the extension needs no settings of its own.
struct RecordingActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable, Sendable {
        /// "12.3 mi"; nil for a sport with no distance (strength, yoga).
        var distance: String?
        /// The speed or pace now ("15.2 mph", "8:05 /mi"); nil when there's none.
        var rate: String?
        /// "Speed", "Pace".
        var rateCaption: String
        var heartRate: Int?
        /// When the clock would have started had it never paused: the elapsed time counts up from here without the app updating it.
        var timerStart: Date
        /// Paused: the elapsed time, shown still.
        var pausedElapsed: TimeInterval?
        /// A live tracking link is running for this recording.
        var sharing: Bool
    }

    /// "Ride", "Run".
    var sport: String
    /// The sport's SF Symbol.
    var symbol: String
}

extension RecordingActivityAttributes.ContentState {
    /// "1:02:03" or "12:34", for the paused clock.
    static func clock(_ seconds: TimeInterval) -> String {
        let s = Int(max(0, seconds))
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60) : String(format: "%d:%02d", s / 60, s % 60)
    }
}
#endif
