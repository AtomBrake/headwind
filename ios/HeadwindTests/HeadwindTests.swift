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
