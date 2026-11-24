import XCTest

/// Records a short ride and a short run on the Watch simulator, checking the map page each has after its figures, and a strength
/// session, which has no map page. Run with a simulated route on the Watch, e.g.
///     xcrun simctl location <watch> start --speed=8 51.4545,-2.5879 51.4645,-2.5879
/// and a paired iPhone simulator with the Headwind app paired to a server to see the ride arrive and upload.
///
/// On a simulator that has never granted Headwind Health access, the first test pages through Apple's permission sheet
/// itself: its buttons are list cells that load only once scrolled into view, and its last page wants a "how far back"
/// choice before Done works.
@MainActor
final class WatchRecordRideUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    func testRecordARideOnTheWatch() throws {
        let app = launch()
        try startRecording(app, sport: "Ride")

        Thread.sleep(forTimeInterval: 40)
        snapshot(app, "w2-riding")

        try checkMapPage(app, name: "ride")
        app.swipeRight()   // back to the figures
        endRecording(app)
    }

    /// A run has the map page too, with its pace over the map.
    func testMapPageOnARun() throws {
        let app = launch()
        try startRecording(app, sport: "Run")
        Thread.sleep(forTimeInterval: 30)
        try checkMapPage(app, name: "run")
        let pace = app.staticTexts.matching(NSPredicate(format: "label ENDSWITH %@ OR label ENDSWITH %@", "/km", "/mi")).firstMatch
        XCTAssertTrue(pace.exists, "No pace over the run's map")
        app.swipeRight()
        endRecording(app)
    }

    /// A timed-only session keeps two pages: controls and figures, no map.
    func testNoMapPageForStrength() throws {
        let app = launch()
        try startRecording(app, sport: "Strength")
        snapshot(app, "strength-figures")
        app.swipeLeft()
        Thread.sleep(forTimeInterval: 1)
        XCTAssertFalse(app.descendants(matching: .any)["watch-map-page"].exists, "A timed-only session has no map page")
        XCTAssertTrue(clock(app).exists, "Swiping left from the figures should stay on them")
        endRecording(app)
    }

    // MARK: - Steps

    private func launch() -> XCUIApplication {
        let app = XCUIApplication()
        app.launch()
        // A ride left over from an earlier run would show its recovery prompt first.
        if app.buttons["Discard"].waitForExistence(timeout: 2) { app.buttons["Discard"].tap() }
        return app
    }

    private func clock(_ app: XCUIApplication) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label MATCHES %@", "^[0-9]+:[0-9]{2}$")).firstMatch
    }

    /// Picks the sport (remembered between launches, so always picked) and starts it, accepting any permission sheets on the way.
    private func startRecording(_ app: XCUIApplication, sport: String) throws {
        let start = app.buttons["watch-start-ride"]
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        let picker = app.buttons["watch-sport-picker"]
        XCTAssertTrue(picker.waitForExistence(timeout: 5))
        picker.tap()
        // The picker is a sheet: let it finish opening, scroll to the sport, and tap until the sheet closes.
        // The list loads its rows as they scroll into view, so one further down isn't there until scrolled to.
        let choice = app.buttons[sport].firstMatch
        _ = choice.waitForExistence(timeout: 3)
        Thread.sleep(forTimeInterval: 1)
        // Down the list first; if it opened scrolled to an earlier choice further down, back up.
        for i in 0..<18 where !(choice.exists && choice.isHittable) { i < 8 ? app.swipeUp() : app.swipeDown() }
        XCTAssertTrue(choice.exists, "No \(sport) in the sport picker")
        for _ in 0..<3 where choice.exists {
            if choice.isHittable { choice.tap() }
            Thread.sleep(forTimeInterval: 1.5)
        }
        for label in ["Close", "Cancel", "Dismiss"] where choice.exists && app.buttons[label].exists {
            app.buttons[label].firstMatch.tap()   // the sport was already chosen, and tapping it again left the sheet open
            Thread.sleep(forTimeInterval: 1)
        }
        XCTAssertTrue(start.waitForExistence(timeout: 5))
        XCTAssertTrue(picker.label.hasSuffix(sport), "Picked \(picker.label), not \(sport)")
        snapshot(app, "w1-start-\(sport.lowercased())")
        start.tap()

        // First run: Health and location permission sheets. Accept whatever appears until the ride is running.
        let deadline = Date().addingTimeInterval(180)   // the Health sheet has several pages
        let carousel = XCUIApplication(bundleIdentifier: "com.apple.Carousel")
        let metrics = clock(app)
        var round = 0
        var pickedHistory = false
        while !metrics.exists && Date() < deadline {
            round += 1
            if round % 5 == 1 { snapshot(app, "w1-waiting-\(round)") }
            let alert = carousel.alerts.firstMatch
            if alert.exists {
                // The Health sheet is a list that loads its rows as they scroll into view, its buttons (cells, not buttons) at the
                // bottom: switch on what's showing, scroll to the end, then press whatever moves it on.
                for toggle in carousel.switches.allElementsBoundByIndex where toggle.isHittable && (toggle.value as? String) == "0" {
                    toggle.tap()
                }
                for _ in 0..<3 { alert.swipeUp() }
                // Read access ends by asking how far back: Done stays greyed until one is picked.
                let history = carousel.descendants(matching: .any).matching(NSPredicate(format: "label == 'Full History'")).firstMatch
                if !pickedHistory, history.exists, history.isHittable {
                    history.tap()
                    pickedHistory = true
                    continue
                }
                let labels = ["Allow While Using App", "Review", "Turn On All", "Allow All", "Next", "Continue", "Allow", "Done"]
                let controls = labels.map { carousel.descendants(matching: .any).matching(NSPredicate(format: "label == %@", $0)).firstMatch }
                    + [carousel.descendants(matching: .any)["UIA.Health.WatchAuthSheet.ConfigureCell.Button"]]   // the sheet's own, whatever it says
                if let control = controls.first(where: { $0.exists && $0.isHittable }) { control.tap() }
            } else if app.buttons["watch-start-ride"].exists && app.buttons["watch-start-ride"].isHittable {
                app.buttons["watch-start-ride"].tap()
            }
            Thread.sleep(forTimeInterval: 1)
        }
        XCTAssertTrue(metrics.exists, "The \(sport.lowercased()) never started")
    }

    /// From the figures, the third page: the map with its figures; the crown zooms it; it survives the app going to the background.
    private func checkMapPage(_ app: XCUIApplication, name: String) throws {
        app.swipeLeft()
        let map = app.descendants(matching: .any)["watch-map-page"]
        XCTAssertTrue(map.waitForExistence(timeout: 5), "No map page after the figures")
        XCTAssertTrue(app.staticTexts["watch-map-distance"].exists, "No distance over the map")
        Thread.sleep(forTimeInterval: 5)   // tiles
        snapshot(app, "map-\(name)")
        XCUIDevice.shared.rotateDigitalCrown(delta: 3)
        Thread.sleep(forTimeInterval: 3)
        snapshot(app, "map-\(name)-crown-in")
        XCUIDevice.shared.rotateDigitalCrown(delta: -6)
        Thread.sleep(forTimeInterval: 3)
        snapshot(app, "map-\(name)-crown-out")
        // Away and back: the page rests, then follows again.
        XCUIDevice.shared.press(.home)
        Thread.sleep(forTimeInterval: 3)
        app.activate()
        XCTAssertTrue(map.waitForExistence(timeout: 10), "The map page went away after the app was in the background")
        Thread.sleep(forTimeInterval: 5)
        snapshot(app, "map-\(name)-back")
        app.swipeLeft()   // the last page: stays on the map
        XCTAssertTrue(map.exists)
    }

    private func endRecording(_ app: XCUIApplication) {
        app.swipeRight()   // controls page
        let end = app.buttons["watch-end-ride"]
        XCTAssertTrue(end.waitForExistence(timeout: 5))
        snapshot(app, "w3-controls")
        end.tap()
        XCTAssertTrue(app.buttons["Done"].waitForExistence(timeout: 30), "No summary after ending")
        Thread.sleep(forTimeInterval: 3)
        snapshot(app, "w4-summary")
        app.buttons["Done"].tap()
    }

    private func snapshot(_ app: XCUIApplication, _ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
