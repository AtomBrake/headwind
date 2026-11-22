import CoreLocation
import XCTest

/// End-to-end: start a recording with "Share live location" on, against a real server. A server with an https outside address gives a link
/// and the share sheet, then Stop sharing ends it; one without (any local test server) refuses with its reason, and the recording goes on
/// without the link. Either way the recording is discarded at the end. Location permission must be granted beforehand, as for
/// RecordRideUITests.
@MainActor
final class LiveShareUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testShareALinkAtStart() throws {
        let (server, token) = try liveServer()
        let device = XCUIDevice.shared
        let start = CLLocationCoordinate2D(latitude: 51.4545, longitude: -2.5879)
        device.location = XCUILocation(location: fix(start, metresNorth: 0))

        let app = launchPaired(server: server, token: token)
        app.tabBars.buttons["Record"].tap()
        XCTAssertTrue(app.staticTexts["GPS ready"].waitForExistence(timeout: 15), "No GPS fix")
        app.buttons["sport-picker"].tap()
        app.buttons["Run"].tap()

        let share = app.switches["share-live"]
        XCTAssertTrue(share.waitForExistence(timeout: 5), "No Share live location switch")
        if share.value as? String != "1" { flip(share) }
        XCTAssertTrue(app.staticTexts["You'll get a link to send. Anyone with the link can see where you are."].waitForExistence(timeout: 3))
        snapshot(app, "l1-switch-on")

        app.buttons["start-ride"].tap()
        XCTAssertTrue(app.buttons["finish-ride"].waitForExistence(timeout: 5))
        for second in 1...5 {
            device.location = XCUILocation(location: fix(start, metresNorth: Double(second) * 3))
            Thread.sleep(forTimeInterval: 1)
        }

        let refused = app.alerts["Live link"]
        let sheet = app.otherElements["ActivityListView"]
        XCTAssertTrue(refused.waitForExistence(timeout: 15) || sheet.exists, "Neither a link nor a refusal")
        snapshot(app, "l2-answer")
        if refused.exists {
            XCTAssertTrue(refused.staticTexts.matching(NSPredicate(format: "label CONTAINS 'outside address'")).firstMatch.exists)
            XCTAssertTrue(refused.staticTexts.matching(NSPredicate(format: "label CONTAINS 'The recording goes on'")).firstMatch.exists)
            XCTAssertTrue(refused.buttons["Open Settings on the server"].exists)
            refused.buttons["OK"].tap()
            XCTAssertEqual(app.switches["share-live"].value as? String, "0", "The switch stays on after a refusal")
            XCTAssertTrue(app.staticTexts["Recording"].exists, "The recording stopped")
        } else {
            app.buttons["Close"].firstMatch.tap()
            XCTAssertTrue(app.buttons["stop-sharing"].waitForExistence(timeout: 5))
            snapshot(app, "l3-sharing")
            app.buttons["stop-sharing"].tap()
            XCTAssertTrue(app.switches["share-live"].waitForExistence(timeout: 10), "Stop sharing didn't end the link")
        }
        snapshot(app, "l4-after")

        app.buttons["finish-ride"].tap()
        app.buttons["Discard run"].tap()
        XCTAssertTrue(app.buttons["start-ride"].waitForExistence(timeout: 5))
    }

    /// A SwiftUI Toggle's element is its whole row, which a tap doesn't flip: tap the switch inside it.
    private func flip(_ toggle: XCUIElement) {
        let inner = toggle.switches.firstMatch
        (inner.exists ? inner : toggle).tap()
    }

    private func fix(_ origin: CLLocationCoordinate2D, metresNorth: Double, speed: Double = 3) -> CLLocation {
        CLLocation(coordinate: CLLocationCoordinate2D(latitude: origin.latitude + metresNorth / 111_195, longitude: origin.longitude),
                   altitude: 20, horizontalAccuracy: 5, verticalAccuracy: 5, course: 0, speed: speed, timestamp: Date())
    }
}
