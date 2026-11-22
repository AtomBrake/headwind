import Foundation

/// The app's version as Settings and the Watch's start screen show it, "0.1.1 (2)": the version from
/// Config/Version.xcconfig, which goes up with every build put on a device, and the build number.
enum AppVersion {
    static var display: String { display(Bundle.main.infoDictionary ?? [:]) }

    static func display(_ info: [String: Any]) -> String {
        let version = info["CFBundleShortVersionString"] as? String
        let build = info["CFBundleVersion"] as? String
        switch (version, build) {
        case let (version?, build?): return "\(version) (\(build))"
        case let (version?, nil): return version
        default: return "–"
        }
    }
}
