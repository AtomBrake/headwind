import Foundation
import Testing
@testable import Headwind

@Test func versionShowsTheBuildNumberBesideIt() {
    #expect(AppVersion.display(["CFBundleShortVersionString": "0.1.1", "CFBundleVersion": "2"]) == "0.1.1 (2)")
    #expect(AppVersion.display(["CFBundleShortVersionString": "0.1.1"]) == "0.1.1")
    #expect(AppVersion.display([:]) == "–")
}

/// Config/Version.xcconfig reaches the built app (the targets mustn't set their own version in the project).
@Test func theBuiltAppCarriesTheVersionFromTheConfig() {
    let info = Bundle.main.infoDictionary ?? [:]
    let version = info["CFBundleShortVersionString"] as? String ?? ""
    #expect(version.split(separator: ".").count == 3)
    #expect(version != "0.1.0")
    #expect(Int(info["CFBundleVersion"] as? String ?? "") ?? 0 > 1)
}
