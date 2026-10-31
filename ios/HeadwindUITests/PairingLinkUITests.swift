import XCTest

/// A headwind://pair link opened from outside the app names its server and waits to be confirmed, so a link on a web page or in a message
/// can't pair the phone unseen. Needs no server: the link is cancelled.
@MainActor
final class PairingLinkUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testAPairingLinkAsksBeforePairing() throws {
        let app = XCUIApplication()
        app.launch()
        if app.tabBars.buttons["Settings"].waitForExistence(timeout: 3) {
            app.tabBars.buttons["Settings"].tap()
            scrollTo(app.buttons["Unpair this phone"], in: app).tap()
            app.buttons["Unpair"].firstMatch.tap()
        }
        XCTAssertTrue(app.staticTexts["Pair with your Headwind"].waitForExistence(timeout: 5))

        app.open(URL(string: "headwind://pair?u=https%3A%2F%2Fsomeone-else.example.net&t=hw_TestOnlyNotARealToken0123456789abcdefghij")!)
        // iOS may ask "Open in Headwind?" first.
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        if springboard.buttons["Open"].waitForExistence(timeout: 3) { springboard.buttons["Open"].tap() }

        let alert = app.alerts["Pair with someone-else.example.net?"]
        XCTAssertTrue(alert.waitForExistence(timeout: 5), "The link paired, or asked without naming its server")
        snapshot(app, "pair-link-alert")
        alert.buttons["Cancel"].tap()

        XCTAssertFalse(alert.waitForExistence(timeout: 1))
        XCTAssertTrue(app.staticTexts["Pair with your Headwind"].exists)
        XCTAssertFalse(app.staticTexts["Checking the server…"].exists)
    }
}
