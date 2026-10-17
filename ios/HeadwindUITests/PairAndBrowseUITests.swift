import XCTest

/// End-to-end: pair through the manual form against a real Headwind, then visit every tab.
/// Needs a running server and a device token, passed in from the shell:
///
///     TEST_RUNNER_HW_SERVER=http://localhost:5001 TEST_RUNNER_HW_TOKEN=hw_... xcodebuild test ...
///
/// Without them the test is skipped. Screenshots are kept in the .xcresult.
@MainActor
final class PairAndBrowseUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testPairAndBrowseEveryTab() throws {
        let (server, token) = try liveServer()
        let app = launchPaired(server: server, token: token) { snapshot($0, "1-pairing") }

        XCTAssertTrue(app.staticTexts["Food diary"].exists)
        snapshot(app, "2-today")
        app.swipeUp()
        snapshot(app, "3-today-scrolled")

        app.tabBars.buttons["Overview"].tap()
        XCTAssertTrue(app.staticTexts["Riding"].waitForExistence(timeout: 10), "Overview didn't load")
        snapshot(app, "4-overview")

        app.tabBars.buttons["Settings"].tap()
        XCTAssertTrue(app.buttons["Unpair this phone"].waitForExistence(timeout: 5))
        snapshot(app, "5-settings")
    }
}
