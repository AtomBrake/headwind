import XCTest

/// Records a short ride on the Watch simulator. Run with a simulated route on the Watch, e.g.
///     xcrun simctl location <watch> start --speed=8 51.4545,-2.5879 51.4645,-2.5879
/// and a paired iPhone simulator with the Headwind app paired to a server to see the ride arrive and upload.
///
/// Known limitation (Xcode 27.1, watchOS 27 simulator): on a simulator that has never granted Headwind Health
/// access, Apple's permission sheet doesn't scroll for synthesized touches or the Digital Crown, so its Allow
/// button never loads and this test times out at "The ride never started". Approve the sheet by hand once on
/// that simulator, then the test runs unattended.
@MainActor
final class WatchRecordRideUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testRecordARideOnTheWatch() throws {
        let app = XCUIApplication()
        app.launch()

        // A ride left over from an earlier run would show its recovery prompt first.
        if app.buttons["Discard"].waitForExistence(timeout: 2) { app.buttons["Discard"].tap() }

        let start = app.buttons["watch-start-ride"]
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        snapshot(app, "w1-start")
        start.tap()

        // First run: Health and location permission sheets. Accept whatever appears until the ride is running.
        let deadline = Date().addingTimeInterval(60)
        let carousel = XCUIApplication(bundleIdentifier: "com.apple.Carousel")
        let metrics = app.staticTexts.matching(NSPredicate(format: "label MATCHES %@", "^[0-9]+:[0-9]{2}$")).firstMatch
        var round = 0
        while !metrics.exists && Date() < deadline {
            round += 1
            if round % 5 == 1 { snapshot(app, "w1-waiting-\(round)") }
            // The Health sheet is a scrolling page with its buttons at the bottom.
            // It only loads its button once scrolled into view, so drag the page up like a finger would.
            if carousel.alerts.firstMatch.exists {
                let from = carousel.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.85))
                from.press(forDuration: 0.05, thenDragTo: carousel.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.15)))
            }
            for source in [app, carousel] {
                for label in ["Review", "Turn On All", "Allow All", "Allow", "Next", "Allow While Using App", "Allow Once"] {
                    let button = source.buttons[label].firstMatch
                    if button.exists && button.isHittable { button.tap() }
                }
                let toggles = source.switches.allElementsBoundByIndex.filter { $0.isHittable && ($0.value as? String) == "0" }
                toggles.forEach { $0.tap() }
            }
            if app.buttons["watch-start-ride"].exists && app.buttons["watch-start-ride"].isHittable {
                app.buttons["watch-start-ride"].tap()
            }
            Thread.sleep(forTimeInterval: 1)
        }
        XCTAssertTrue(metrics.exists, "The ride never started")

        Thread.sleep(forTimeInterval: 40)
        snapshot(app, "w2-riding")

        app.swipeRight()   // controls page
        let end = app.buttons["watch-end-ride"]
        XCTAssertTrue(end.waitForExistence(timeout: 5))
        snapshot(app, "w3-controls")
        end.tap()

        XCTAssertTrue(app.buttons["Done"].waitForExistence(timeout: 30), "No summary after ending")
        Thread.sleep(forTimeInterval: 3)
        snapshot(app, "w4-summary")
    }

    private func snapshot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
