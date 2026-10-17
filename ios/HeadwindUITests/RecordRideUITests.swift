import CoreLocation
import XCTest

/// End-to-end: record a short ride from simulated GPS, finish it, and wait for the real server to accept the GPX.
/// Location permission must be granted beforehand (xcrun simctl privacy <device> grant location <bundle id>).
@MainActor
final class RecordRideUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testRecordAndUploadARide() throws {
        let (server, token) = try liveServer()
        let device = XCUIDevice.shared
        // A start fix before opening the tab, so "GPS ready" can appear.
        let start = CLLocationCoordinate2D(latitude: 51.4545, longitude: -2.5879)
        device.location = XCUILocation(location: fix(start, metresNorth: 0))

        let app = launchPaired(server: server, token: token)
        app.tabBars.buttons["Record"].tap()
        XCTAssertTrue(app.staticTexts["GPS ready"].waitForExistence(timeout: 15), "No GPS fix")
        snapshot(app, "r1-ready")

        app.buttons["start-ride"].tap()
        XCTAssertTrue(app.buttons["finish-ride"].waitForExistence(timeout: 5))

        // Ride north for ~40 s at 8 m/s (29 km/h), one fix a second.
        for second in 1...40 {
            device.location = XCUILocation(location: fix(start, metresNorth: Double(second) * 8))
            Thread.sleep(forTimeInterval: 1)
        }
        snapshot(app, "r2-recording")

        app.buttons["finish-ride"].tap()
        app.buttons["Save ride"].tap()
        XCTAssertTrue(app.staticTexts["Uploaded to Headwind"].waitForExistence(timeout: 60)
                      || app.staticTexts["Already on the server"].exists, "Upload didn't complete")
        snapshot(app, "r3-uploaded")

        app.buttons["Done"].tap()
        app.buttons["recordings"].tap()
        XCTAssertTrue(app.staticTexts["Uploaded to Headwind"].waitForExistence(timeout: 5))
        snapshot(app, "r4-recordings")
    }

    private func fix(_ origin: CLLocationCoordinate2D, metresNorth: Double) -> CLLocation {
        CLLocation(coordinate: CLLocationCoordinate2D(latitude: origin.latitude + metresNorth / 111_195, longitude: origin.longitude),
                   altitude: 20 + metresNorth / 40, horizontalAccuracy: 5, verticalAccuracy: 5,
                   course: 0, speed: 8, timestamp: Date())
    }
}
