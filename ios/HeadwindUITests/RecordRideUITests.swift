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
        choose(app, "sport-picker", "Ride")     // the last sport chosen is remembered, perhaps by another test
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

    /// Pick a sport (and a bike) before Start, record, and check the upload went where that sport goes.
    func testRecordAWalkThenAnEbikeRideOnAChosenBike() throws {
        let (server, token) = try liveServer()
        let device = XCUIDevice.shared
        let start = CLLocationCoordinate2D(latitude: 51.4545, longitude: -2.5879)
        device.location = XCUILocation(location: fix(start, metresNorth: 0, speed: 1.5))

        let app = launchPaired(server: server, token: token)
        app.tabBars.buttons["Record"].tap()
        XCTAssertTrue(app.staticTexts["GPS ready"].waitForExistence(timeout: 15), "No GPS fix")

        choose(app, "sport-picker", "Walk")
        XCTAssertFalse(app.buttons["bike-picker"].exists, "No bike on foot")
        record(app, from: start, seconds: 30, speed: 1.5, startLabel: "Start walk")
        XCTAssertTrue(app.staticTexts["Pace"].exists)
        app.buttons["finish-ride"].tap()
        app.buttons["Save walk"].tap()
        XCTAssertTrue(app.staticTexts["Uploaded to Headwind"].waitForExistence(timeout: 60), "Walk upload didn't complete")
        snapshot(app, "s1-walk-uploaded")
        app.buttons["Done"].tap()

        let later = CLLocationCoordinate2D(latitude: 51.47, longitude: -2.5879)
        device.location = XCUILocation(location: fix(later, metresNorth: 0))
        choose(app, "sport-picker", "E-bike ride")
        choose(app, "bike-picker", "Test E-bike")
        snapshot(app, "s2-ebike-chosen")
        record(app, from: later, seconds: 30, speed: 8, startLabel: "Start e-bike ride")
        app.buttons["finish-ride"].tap()
        app.buttons["Save e-bike ride"].tap()
        XCTAssertTrue(app.staticTexts["Uploaded to Headwind"].waitForExistence(timeout: 60), "Ride upload didn't complete")
        app.buttons["Done"].tap()
        app.buttons["recordings"].tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label ENDSWITH 'Walk'")).firstMatch.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label ENDSWITH 'E-bike Ride'")).firstMatch.exists)
        snapshot(app, "s3-recordings")
    }

    private func choose(_ app: XCUIApplication, _ picker: String, _ option: String) {
        app.buttons[picker].tap()
        let item = app.buttons[option]
        XCTAssertTrue(item.waitForExistence(timeout: 5), "No \(option) in \(picker)")
        item.tap()
    }

    private func record(_ app: XCUIApplication, from origin: CLLocationCoordinate2D, seconds: Int, speed: Double, startLabel: String) {
        XCTAssertTrue(app.buttons["start-ride"].label.contains(startLabel), "Start button says \(app.buttons["start-ride"].label)")
        app.buttons["start-ride"].tap()
        XCTAssertTrue(app.buttons["finish-ride"].waitForExistence(timeout: 5))
        for second in 1...seconds {
            XCUIDevice.shared.location = XCUILocation(location: fix(origin, metresNorth: Double(second) * speed, speed: speed))
            Thread.sleep(forTimeInterval: 1)
        }
    }

    private func fix(_ origin: CLLocationCoordinate2D, metresNorth: Double, speed: Double = 8) -> CLLocation {
        CLLocation(coordinate: CLLocationCoordinate2D(latitude: origin.latitude + metresNorth / 111_195, longitude: origin.longitude),
                   altitude: 20 + metresNorth / 40, horizontalAccuracy: 5, verticalAccuracy: 5,
                   course: 0, speed: speed, timestamp: Date())
    }
}
