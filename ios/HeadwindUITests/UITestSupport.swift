import XCTest

@MainActor
extension XCTestCase {
    /// Server and token for a live Headwind, passed from the shell as TEST_RUNNER_HW_SERVER / TEST_RUNNER_HW_TOKEN
    /// (xcodebuild strips the prefix). Skips the test when they're not set.
    func liveServer() throws -> (server: String, token: String) {
        let env = ProcessInfo.processInfo.environment
        guard let server = env["HW_SERVER"], let token = env["HW_TOKEN"] else {
            throw XCTSkip("Set TEST_RUNNER_HW_SERVER and TEST_RUNNER_HW_TOKEN to run against a server.")
        }
        return (server, token)
    }

    /// Launches the app and pairs it through the manual form, unpairing first if a previous run left it paired.
    func launchPaired(server: String, token: String, onPairingScreen: (XCUIApplication) -> Void = { _ in }) -> XCUIApplication {
        let app = XCUIApplication()
        app.launch()

        if app.tabBars.buttons["Settings"].waitForExistence(timeout: 3) {
            app.tabBars.buttons["Settings"].tap()
            app.buttons["Unpair this phone"].tap()
            app.buttons["Unpair"].firstMatch.tap()
        }

        XCTAssertTrue(app.staticTexts["Pair with your Headwind"].waitForExistence(timeout: 5))
        onPairingScreen(app)

        app.buttons["Enter details manually"].tap()
        let serverField = app.textFields["https://bike.example.com"]
        serverField.tap()
        serverField.typeText(server)
        let tokenField = app.textFields["Token (hw_…) or pairing link"]
        tokenField.tap()
        tokenField.typeText(token)
        app.buttons["Pair"].tap()

        XCTAssertTrue(app.staticTexts["Calories"].waitForExistence(timeout: 10), "Today didn't load after pairing")
        return app
    }

    func snapshot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
