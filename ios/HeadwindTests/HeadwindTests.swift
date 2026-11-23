import Foundation
import Testing
@testable import Headwind

struct PairLinkTests {
    let token = "hw_TestOnlyNotARealToken0123456789abcdefghij"

    /// The message of the AppError `body` throws, or nil if it succeeds.
    private func failure(_ body: () throws(AppError) -> Pairing) -> String? {
        do throws(AppError) {
            _ = try body()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    @Test func parsesTheLinkThePhonesPageMakes() throws {
        // routes/phones.py: f"headwind://pair?u={quote(url, safe='')}&t={token}"
        let p = try PairLink.parse("headwind://pair?u=https%3A%2F%2Fbike.example.com%2Fhw&t=\(token)")
        #expect(p.server.absoluteString == "https://bike.example.com/hw")
        #expect(p.token == token)
    }

    @Test func trimsWhitespaceAndTrailingSlashes() throws {
        let p = try PairLink.make(server: "  https://bike.example.com//\n", token: " \(token) ")
        #expect(p.server.absoluteString == "https://bike.example.com")
        #expect(p.token == token)
    }

    @Test func rejectsOtherLinks() {
        #expect(failure { () throws(AppError) in try PairLink.parse("https://bike.example.com") } == AppError.notAPairingLink.localizedDescription)
        #expect(failure { () throws(AppError) in try PairLink.parse("headwind://open?u=x") } == AppError.notAPairingLink.localizedDescription)
    }

    @Test func rejectsPlainHTTPExceptLocalDebug() throws {
        #expect(failure { () throws(AppError) in try PairLink.make(server: "http://bike.example.com", token: token) } == AppError.insecureServer.localizedDescription)
        #expect(failure { () throws(AppError) in try PairLink.make(server: "http://192.168.1.20:5001", token: token) } == AppError.insecureServer.localizedDescription)
        #expect(throws: (any Error).self) { try PairLink.make(server: "ftp://localhost", token: token) }
        if PairLink.allowsLocalHTTP {
            #expect(try PairLink.make(server: "http://localhost:5001", token: token).server.port == 5001)
        }
    }

    @Test func rejectsMissingOrMalformedTokens() {
        #expect(failure { () throws(AppError) in try PairLink.make(server: "https://a.example", token: "") } == AppError.badToken.localizedDescription)
        #expect(failure { () throws(AppError) in try PairLink.make(server: "https://a.example", token: "abc_123456789012345678901") } == AppError.badToken.localizedDescription)
        #expect(failure { () throws(AppError) in try PairLink.parse("headwind://pair?u=https%3A%2F%2Fa.example") } == AppError.badToken.localizedDescription)
        #expect(failure { () throws(AppError) in try PairLink.make(server: "", token: token) } == AppError.missingServer.localizedDescription)
    }
}

struct DecodingTests {
    private func fixture(_ name: String) throws -> Data {
        let url = try #require(Bundle(for: BundleMarker.self).url(forResource: name, withExtension: "json"))
        return try Data(contentsOf: url)
    }

    @Test func decodesPing() throws {
        let ping = try JSONDecoder.headwind.decode(PingInfo.self, from: fixture("ping"))
        #expect(ping.api == 1)
        #expect(ping.units == "metric")
        #expect(ping.calorieAdjustPct == 0)
        #expect(ping.serverUrl == "https://headwind.example.com")
    }

    @Test func decodesToday() throws {
        let today = try JSONDecoder.headwind.decode(Today.self, from: fixture("today"))
        #expect(today.goals?.cal == 2400)
        #expect(today.eaten?.calories == 1005)
        #expect(today.waterMl == 1250)
        #expect(today.waterGoalMl == 2500)
        #expect(today.burnSource == "BMR (resting)")
        #expect(today.steps?.goal == 9000)
        #expect(today.weight?.unit == "stlb")
        #expect(today.entries?.count == 3)
        #expect(today.entries?.first?.foodName == "Porridge oats")
        #expect(today.entries?.first?.mealType == "breakfast")
    }

    @Test func decodesOverview() throws {
        let o = try JSONDecoder.headwind.decode(Overview.self, from: fixture("overview"))
        #expect(o.all.rides == 60)
        #expect(o.weekly.count == 12)
        #expect(o.weekly.last?.current == true)
        #expect(o.workouts?["week"]?.count == 0)
        #expect(o.recovery?.restingHR == 48)
        #expect(o.title(for: .week) == "Week")             // an older server sends no periods: the app's own words
        #expect(o.caption(for: .week) == nil)
    }

    @Test func overviewSaysWhatTheServerCountsAsAWeek() throws {
        let t = #"{"rides":0,"distance_m":0,"elev_m":0,"moving_s":0,"calories":0}"#
        let json = #"{"all":\#(t),"week":\#(t),"month":\#(t),"year":\#(t),"weekly":[],"periods":{"#
            + #""week":{"label":"Past 7 days","short":"7 days","dates":"17–23 Nov","from":"2026-11-17","to":"2026-11-23","days":7,"mode":"rolling"},"#
            + #""month":{"label":"November","short":"Month","dates":"Nov 2026","from":"2026-11-01","to":"2026-11-30","days":30,"mode":"calendar"},"#
            + #""year":{"label":"2026","short":"Year","dates":"2026","from":"2026-01-01","to":"2026-12-31","days":365,"mode":"rolling"}}}"#
        let o = try JSONDecoder.headwind.decode(Overview.self, from: Data(json.utf8))
        #expect(o.title(for: .week) == "7 days")
        #expect(o.caption(for: .week) == "Past 7 days · 17–23 Nov")
        #expect(o.caption(for: .year) == "2026")
        #expect(o.title(for: .all) == "All time" && o.caption(for: .all) == nil)
    }

    @Test func decodesAFreshInstallWithNothingSet() throws {
        // No goals, no weight, no Garmin: the server sends nulls and empty lists rather than omitting the screen.
        let json = """
        {"date":"2026-10-17","rider":"New","goals":{"cal":null,"protein":null,"water":null},"eaten":{"calories":0,"protein":0,"carbs":0,"fat":0,"fibre":0},
         "remaining":{"calories":null,"protein":null},"water_ml":0,"water_goal_ml":null,"burned":null,"burn_source":null,
         "steps":{"today":null,"goal":8000},"weight":{"raw":null,"trend":null,"unit":"kg"},"entries":[],"recent":[],"favourites":[],"workouts":[]}
        """
        let today = try JSONDecoder.headwind.decode(Today.self, from: Data(json.utf8))
        #expect(today.goals?.cal == nil)
        #expect(today.steps?.today == nil)
        #expect(today.entries?.isEmpty == true)
    }
}

/// The server's outside address from /ping, when it isn't the one this phone paired with (Session.movedServer).
@MainActor
struct ServerMoveTests {
    private let token = "hw_" + String(repeating: "a", count: 32)

    private func session(pairedWith server: String, pingSays serverUrl: String?, defaults: UserDefaults) throws -> Session {
        defaults.set(try JSONEncoder().encode(PingInfo(serverUrl: serverUrl)), forKey: "ping-info")
        return Session(store: MemoryPairingStore(Pairing(server: URL(string: server)!, token: token)), defaults: defaults)
    }

    private func freshDefaults() -> UserDefaults {
        let name = "ServerMoveTests-\(UUID().uuidString)"
        let d = UserDefaults(suiteName: name)!
        d.removePersistentDomain(forName: name)
        return d
    }

    @Test func offersTheNewAddress() throws {
        let s = try session(pairedWith: "https://192.168.1.5", pingSays: "https://headwind.example.com", defaults: freshDefaults())
        #expect(s.movedServer == URL(string: "https://headwind.example.com"))
    }

    @Test func notWhenItsTheSameOrThereIsNoneOrItIsntHTTPS() throws {
        #expect(try session(pairedWith: "https://Headwind.example.com", pingSays: "https://headwind.example.com/", defaults: freshDefaults()).movedServer == nil)
        #expect(try session(pairedWith: "https://headwind.example.com", pingSays: nil, defaults: freshDefaults()).movedServer == nil)
        #expect(try session(pairedWith: "https://headwind.example.com", pingSays: "http://192.168.1.5", defaults: freshDefaults()).movedServer == nil)
    }

    @Test func notNowIsRemembered() throws {
        let defaults = freshDefaults()
        let s = try session(pairedWith: "https://192.168.1.5", pingSays: "https://headwind.example.com", defaults: defaults)
        s.declineMove()
        #expect(s.movedServer == nil)
        #expect(try session(pairedWith: "https://192.168.1.5", pingSays: "https://headwind.example.com", defaults: defaults).movedServer == nil)
        #expect(try session(pairedWith: "https://192.168.1.5", pingSays: "https://other.example.com", defaults: defaults).movedServer != nil,
                "another new address is offered again")
    }
}

struct UnitsTests {
    @Test func distanceFollowsTheServerSetting() {
        #expect(Units(system: "metric").distance(metres: 42_195) == "42.2 km")
        #expect(Units(system: "imperial").distance(metres: 160_934.4) == "100 mi")
        #expect(Units(system: "imperial").elevation(metres: 100) == "328 ft")
    }

    @Test func weightInStonesAndPounds() {
        #expect(Units.weight(kg: 77.9, unit: "stlb") == "12 st 3.7 lb")
        #expect(Units.weight(kg: 77.9, unit: "kg") == "77.9 kg")
        #expect(Units.weight(kg: 63.5, unit: "stlb") == "10 st 0.0 lb")   // 13.99.. lb must not print as "9 st 14.0 lb"
    }

    @Test func durations() {
        #expect(Units.duration(seconds: 3 * 3600 + 5 * 60) == "3h 05m")
        #expect(Units.duration(seconds: 59 * 60) == "59m")
        #expect(Units.duration(seconds: 39) == "39s")
        #expect(Units.clock(seconds: 3727) == "1:02:07")
        #expect(Units.clock(seconds: 41) == "0:41")
    }
}

private final class BundleMarker {}

struct FriendLinkTests {
    let code = "hwfc_eyJ1IjoiaHR0cHM6Ly9zYW0uZXhhbXBsZSIsInQiOiJod2ZfYWJjIn0"

    @Test func readsTheCodeAndTheLinkInTheQR() {
        // services/feed_tokens.py: share_code, and share_link = "headwind://friend?c=" + code
        #expect(FriendLink.code(in: code) == code)
        #expect(FriendLink.code(in: "  \(code)\n") == code)
        #expect(FriendLink.code(in: "headwind://friend?c=\(code)") == code)
    }

    @Test func refusesWhatIsntOne() {
        #expect(FriendLink.code(in: "hwf_aFeedTokenNotACode0123456789") == nil)
        #expect(FriendLink.code(in: "headwind://pair?u=https%3A%2F%2Fa.example&t=hw_x") == nil)
        #expect(FriendLink.code(in: "headwind://friend?c=nonsense") == nil)
        #expect(FriendLink.code(in: "hwfc_") == nil)
    }

    @Test func aFriendLinkIsntTakenForPairing() async {
        let session = await Session(store: MemoryPairingStore())
        await session.handle(url: URL(string: "headwind://friend?c=\(code)")!)
        #expect(await session.pendingFriendCode == code)
        #expect(await session.pendingLink == nil)
    }

    @Test func quickRangesLeaveTheEndOpen() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "Europe/London")!
        let now = cal.date(from: DateComponents(year: 2026, month: 10, day: 31, hour: 23, minute: 30))!
        let picked = cal.date(from: DateComponents(year: 2026, month: 3, day: 1, hour: 0, minute: 10))!
        #expect(ShareRange.all.window(since: picked, until: nil, now: now, calendar: cal) == (nil, nil))
        #expect(ShareRange.month.window(since: picked, until: nil, now: now, calendar: cal) == ("2026-09-30", nil))
        #expect(ShareRange.today.window(since: picked, until: nil, now: now, calendar: cal) == ("2026-10-31", nil))
        #expect(ShareRange.custom.window(since: picked, until: now, now: now, calendar: cal) == ("2026-03-01", "2026-10-31"))
    }
}
