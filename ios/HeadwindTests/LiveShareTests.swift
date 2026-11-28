import Foundation
import Testing
@testable import Headwind

/// Fixes one a second, heading north at `metresPerSecond`.
private func track(seconds: Int, metresPerSecond: Double = 6, from start: Date = Date(timeIntervalSince1970: 1_760_000_000)) -> [RidePoint] {
    (0..<seconds).map { i in
        RidePoint(time: start.addingTimeInterval(Double(i)), lat: 51.5 + Double(i) * metresPerSecond / 111_195.0, lon: -0.1, accuracy: 5)
    }
}

private func json(_ value: some Encodable) throws -> [String: Any] {
    try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(value)) as? [String: Any])
}

private func tempDefaults() -> UserDefaults {
    let name = "headwind-live-tests-\(UUID().uuidString)"
    let d = UserDefaults(suiteName: name)!
    d.removePersistentDomain(forName: name)
    return d
}

struct LiveTrackTests {
    @Test func keepsAPointEveryTenSecondsOrTwentyFiveMetres() {
        // 6 m/s: 25 m comes after 5 s (30 m), before 10 s does.
        let thinned = LiveTrack.thinned(track(seconds: 61))
        #expect(thinned.count == 13)                       // 0, 5, 10 ... 60
        #expect(thinned[1][2] - thinned[0][2] == 5)
        // 1.5 m/s: 10 s comes first (15 m).
        let slow = LiveTrack.thinned(track(seconds: 61, metresPerSecond: 1.5))
        #expect(slow.count == 7)                           // 0, 10 ... 60
    }

    @Test func dropsStandingStill() {
        let still = (0..<120).map { i in
            RidePoint(time: Date(timeIntervalSince1970: 1_760_000_000 + Double(i)), lat: 51.5, lon: -0.1, accuracy: 5)
        }
        #expect(LiveTrack.thinned(still).count == 1)
    }

    @Test func capsAtTheLimitEndingWhereTheRiderIs() {
        let long = track(seconds: 2_000, metresPerSecond: 30)      // every point is 30 m on: none thinned away
        let capped = LiveTrack.thinned(long, limit: 100)
        #expect(capped.count == 100)
        #expect(capped.first?[0] == long.first?.lat)
        #expect(capped.last?[0] == long.last?.lat)
        #expect(zip(capped, capped.dropFirst()).allSatisfy { $0[2] < $1[2] })
    }

    @Test func pointsAreLatLngAndEpochSeconds() throws {
        let p = try #require(LiveTrack.thinned(track(seconds: 1)).first)
        #expect(p == [51.5, -0.1, 1_760_000_000])
    }
}

struct LiveCadenceTests {
    @Test func everyFifteenSecondsOrFiveWhileSharing() {
        #expect(LiveCadence.phone(sharing: false) == 15)
        #expect(LiveCadence.phone(sharing: false, sendEvery: 5) == 15)
        #expect(LiveCadence.phone(sharing: true) == 5)
        #expect(LiveCadence.phone(sharing: true, sendEvery: 5) == 5)
        #expect(LiveCadence.phone(sharing: true, sendEvery: 8) == 8)
        #expect(LiveCadence.phone(sharing: true, sendEvery: 0.1) == 1)      // never hammered
        #expect(LiveCadence.phone(sharing: true, sendEvery: 600) == 15)     // never slower than without a link
        #expect(LiveCadence.phone(sharing: true, sendEvery: -1) == 5)
        #expect(LiveCadence.watch == 30)
    }

    @Test func dueAfterTheIntervalOrWhenForced() {
        let last = Date(timeIntervalSince1970: 1_000)
        #expect(!LiveCadence.due(last: last, now: last.addingTimeInterval(4), interval: 5))
        #expect(LiveCadence.due(last: last, now: last.addingTimeInterval(5), interval: 5))
        #expect(LiveCadence.due(last: last, now: last.addingTimeInterval(1), interval: 30, force: true))
        #expect(LiveCadence.due(last: .distantPast, interval: 30))
    }
}

struct LiveShareBodyTests {
    @Test func liveUpdateCarriesTheRecording() throws {
        let id = UUID()
        let body = try json(LiveUpdate(state: "riding", recording: id.uuidString, lat: 51.5, lng: -0.1, speed_mps: 5, distance_m: 100,
                                       elapsed_s: 20, alt_m: nil, accuracy_m: 5, sport: "Run", battery_pct: 80))
        #expect(body["recording"] as? String == id.uuidString)
        #expect(body["state"] as? String == "riding")
        #expect(body["alt_m"] == nil)
    }

    @Test func idleEndsTheRecordingsLink() throws {
        let id = UUID()
        let body = try json(LiveUpdate.idle(recording: id, sport: .hike, distance: 1_234, elapsed: 600.7, battery: nil))
        #expect(body["state"] as? String == "idle")
        #expect(body["recording"] as? String == id.uuidString)
        #expect(body["sport"] as? String == "Hike")
        #expect(body["elapsed_s"] as? Int == 600)
        #expect(body["lat"] == nil)
    }

    @Test func shareAtStartSendsNoTrack() throws {
        let id = UUID()
        let body = try json(LiveShareController.request(recording: id, sport: .run, track: []))
        #expect(body["recording"] as? String == id.uuidString)
        #expect(body["sport"] as? String == "Run")
        #expect(body["track"] == nil)
    }

    @Test func shareMidRecordingSendsTheTrackThinned() throws {
        let body = try json(LiveShareController.request(recording: UUID(), sport: .ride, track: track(seconds: 61)))
        let sent = try #require(body["track"] as? [[Double]])
        #expect(sent.count == 13)
        #expect(sent[0] == [51.5, -0.1, 1_760_000_000])
    }

    @Test func stopNamesTheRecording() throws {
        #expect(try json(LiveShareStop(recording: "abc")) as NSDictionary == ["recording": "abc"])
    }

    @Test func stopIsADeleteWithAJSONBody() throws {
        let client = APIClient(pairing: Pairing(server: URL(string: "https://example.com")!, token: "hw_x"))
        let req = try client.jsonRequest("live/share", method: "DELETE", json: LiveShareStop(recording: "abc"))
        #expect(req.httpMethod == "DELETE")
        #expect(req.url?.absoluteString == "https://example.com/api/v1/live/share")
        #expect(req.value(forHTTPHeaderField: "Content-Type") == "application/json")
        #expect(req.httpBody.flatMap { String(data: $0, encoding: .utf8) } == #"{"recording":"abc"}"#)
    }

    @Test func readsTheServersReply() throws {
        let data = Data(#"{"id": 7, "url": "https://example.com/live/hwl_abc", "recording": "R1", "expires_at": 1760021600.5, "ended": false, "send_every_s": 5, "created": true}"#.utf8)
        let reply = try APIClient.reply(data, status: 201, as: LiveShareReply.self)
        #expect(reply.url.absoluteString == "https://example.com/live/hwl_abc")
        #expect(reply.expiresAt == 1_760_021_600.5)
        #expect(reply.sendEveryS == 5)
        #expect(reply.created == true)
    }

    @Test func readsWhoTheServerIsEmailingItTo() throws {
        let data = Data(#"{"id": 7, "url": "https://example.com/live/hwl_abc", "recording": "R1", "expires_at": 1760021600, "ended": false, "send_every_s": 5, "created": true, "contacts": [{"name": "Sam", "state": "sending", "error": null}, {"name": "Jo", "state": "failed", "error": "Email isn't set up."}]}"#.utf8)
        let reply = try APIClient.reply(data, status: 201, as: LiveShareReply.self)
        #expect(reply.contacts == [LiveShareRecipient(name: "Sam", state: "sending"), LiveShareRecipient(name: "Jo", state: "failed", error: "Email isn't set up.")])
        #expect(!LiveRecipients.settled(try #require(reply.contacts)))
        #expect(LiveRecipients.anyReached(reply.contacts))
        let older = Data(#"{"id": 7, "url": "https://example.com/live/hwl_abc", "recording": "R1", "expires_at": 1760021600, "ended": false}"#.utf8)
        #expect(try APIClient.reply(older, status: 200, as: LiveShareReply.self).contacts == nil)      // a server from before
    }

    @Test func saysWhoItWentTo() {
        let sam = LiveShareRecipient(name: "Sam", state: "sent"), alex = LiveShareRecipient(name: "Alex", state: "sent")
        let jo = LiveShareRecipient(name: "Jo", state: "failed", error: "The mail server would not send to this address.")
        let pat = LiveShareRecipient(name: "Pat", state: "sending")
        #expect(LiveRecipients.summary([]) == nil)
        #expect(LiveRecipients.summary([sam, alex]) == "Sent to Sam and Alex.")
        #expect(LiveRecipients.summary([pat]) == "Emailing Pat…")
        #expect(LiveRecipients.summary([sam, jo]) == "Sent to Sam. Couldn't send to Jo: The mail server would not send to this address.")
        #expect(LiveRecipients.names(["Sam", "Alex", "Jo"]) == "Sam, Alex and Jo")
        #expect(LiveRecipients.settled([sam, jo]))
        #expect(!LiveRecipients.anyReached([jo]))
        #expect(!LiveRecipients.anyReached(nil))
    }

    @Test func refusalPointsAtTheServersSettings() throws {
        let data = Data(#"{"error": "Headwind has no outside address.", "settings_url": "/settings#address"}"#.utf8)
        let refusal = try JSONDecoder.headwind.decode(LiveShareRefusal.self, from: data)
        #expect(refusal.error == "Headwind has no outside address.")
        #expect(refusal.settings(on: URL(string: "https://bike.example.com")!)?.absoluteString == "https://bike.example.com/settings#address")
        #expect(LiveShareRefusal(error: "x", settingsUrl: nil).settings(on: URL(string: "https://bike.example.com")!) == nil)
    }
}

@MainActor
struct LiveShareControllerTests {
    @Test func defaultComesFromSettingsAndComesBackAfterARecording() {
        let defaults = tempDefaults()
        let live = LiveShareController(defaults: defaults)
        #expect(!live.wanted)
        live.shareByDefault = true
        #expect(live.wanted)
        live.wanted = false                                     // switched off on the Record screen for one recording
        live.recordingEnded(UUID())
        #expect(live.wanted)
        #expect(LiveShareController(defaults: defaults).wanted)  // kept
    }

    @Test func noLinkUntilOneIsMade() {
        let live = LiveShareController(defaults: tempDefaults())
        #expect(live.current() == nil)
        #expect(!live.isSharing(nil))
    }
}

struct LiveLinkMessageTests {
    private let reply = LiveShareReply(id: 1, url: URL(string: "https://example.com/live/hwl_abc")!, recording: "R", expiresAt: 1_760_021_600,
                                       ended: false, sendEveryS: 5, created: true)

    @Test func aLinkFromTheWatchSurvivesTheTrip() throws {
        let id = UUID()
        let sent = LiveLinkMessage.started(recording: id, reply: reply, sport: .run)
        let got = try #require(LiveLinkMessage(dictionary: sent.dictionary))
        #expect(got == sent)
        #expect(got.recording == id.uuidString)
        #expect(got.url == reply.url)
        #expect(got.sport == "Run")
        #expect(!got.ended)
    }

    @Test func soDoesItsEnd() throws {
        let id = UUID()
        let got = try #require(LiveLinkMessage(dictionary: LiveLinkMessage.ended(recording: id).dictionary))
        #expect(got.ended)
        #expect(got.url == nil)
    }

    @Test func soDoesItsStopFromTheWatch() throws {
        let id = UUID()
        let got = try #require(LiveLinkMessage(dictionary: LiveLinkMessage.stopped(recording: id).dictionary))
        #expect(got.stopped)
        #expect(got.ended)                                  // what a phone app from before reads: finished
        #expect(LiveLinkMessage(dictionary: LiveLinkMessage.ended(recording: id).dictionary)?.stopped == false)
    }

    @Test func whoTheServerEmailedItToTravelsWithIt() throws {
        let recipients = [LiveShareRecipient(name: "Sam", state: "sent"), LiveShareRecipient(name: "Jo", state: "failed", error: "No.")]
        let sent = LiveLinkMessage.started(recording: UUID(), reply: reply, sport: .ride, recipients: recipients)
        let got = try #require(LiveLinkMessage(dictionary: sent.dictionary))
        #expect(got.recipients == recipients)
        #expect(LiveLinkMessage(dictionary: LiveLinkMessage.started(recording: UUID(), reply: reply, sport: .ride).dictionary)?.recipients == nil)
    }

    @Test func anythingElseIsIgnored() {
        #expect(LiveLinkMessage(dictionary: [:]) == nil)
        #expect(LiveLinkMessage(dictionary: ["recording": "R"]) == nil)                    // a link with no address
        #expect(LiveLinkMessage(dictionary: ["recording": "", "ended": true]) == nil)
    }
}

@MainActor
struct WatchLinkOnThePhoneTests {
    private func message(_ id: String, expires: Date = .now.addingTimeInterval(6 * 3600)) -> LiveLinkMessage {
        LiveLinkMessage(recording: id, url: URL(string: "https://example.com/live/hwl_\(id)")!, expiresAt: expires.timeIntervalSince1970,
                        sport: "Hike")
    }

    @Test func isKeptAndOfferedWhenItsNotificationIsTapped() throws {
        let live = LiveShareController(defaults: tempDefaults())
        live.adopt(fromWatch: message("W1"))
        let link = try #require(live.current())
        #expect(link.recording == "W1")
        #expect(link.fromWatch == true)
        #expect(!link.ended)
        #expect(live.outgoing == nil)                       // waits for the tap: the phone may be in a pocket
        live.offer(recording: "W1")
        #expect(live.outgoing?.url.absoluteString == "https://example.com/live/hwl_W1")
        #expect(live.outgoing?.sport == .hike)
    }

    @Test func endsWithinTheHourWhenTheWatchSaysSo() throws {
        let live = LiveShareController(defaults: tempDefaults())
        live.adopt(fromWatch: message("W2"))
        live.adopt(fromWatch: .ended(recording: try #require(UUID(uuidString: "00000000-0000-0000-0000-000000000000"))))
        #expect(live.current()?.ended == false)             // another recording's end changes nothing
        live.adopt(fromWatch: LiveLinkMessage(recording: "W2", ended: true))
        let link = try #require(live.current())
        #expect(link.ended)
        #expect(link.expiresAt <= Date().addingTimeInterval(LiveShareController.afterEnd))
    }

    @Test func isDroppedWhenStoppedOnTheWatch() throws {
        let live = LiveShareController(defaults: tempDefaults())
        live.adopt(fromWatch: message("W6"))
        live.adopt(fromWatch: LiveLinkMessage(recording: "W7", ended: true, stopped: true))
        #expect(live.current()?.recording == "W6")          // another recording's stop changes nothing
        live.adopt(fromWatch: LiveLinkMessage(recording: "W6", ended: true, stopped: true))
        #expect(live.current() == nil)
    }

    @Test func learnsWhoItWentToWhenTheWatchSaysAgain() throws {
        let live = LiveShareController(defaults: tempDefaults())
        var first = message("W5")
        first.recipients = [LiveShareRecipient(name: "Sam", state: "sending")]
        live.adopt(fromWatch: first)
        #expect(live.current()?.recipients?.first?.isSending == true)
        var settled = first
        settled.recipients = [LiveShareRecipient(name: "Sam", state: "sent")]
        live.adopt(fromWatch: settled)
        let link = try #require(live.current())
        #expect(link.recipients == [LiveShareRecipient(name: "Sam", state: "sent")])
        #expect(link.url == first.url)
    }

    @Test func anExpiredOneOrAnotherRecordingsTapIsIgnored() {
        let live = LiveShareController(defaults: tempDefaults())
        live.adopt(fromWatch: message("old", expires: .now.addingTimeInterval(-60)))
        #expect(live.current() == nil)
        live.adopt(fromWatch: message("W3"))
        live.offer(recording: "W4")
        #expect(live.outgoing == nil)
    }
}

struct RecordingIDTests {
    @Test func theJournalKeepsTheRecordingsID() {
        let journal = RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "journal-\(UUID().uuidString).jsonl"))
        defer { journal.clear() }
        let id = UUID()
        let points = track(seconds: 5)
        journal.begin(start: points[0].time, sport: .run, id: id)
        for p in points { journal.append(p) }
        #expect(journal.load()?.id == id)
    }

    @Test func anOlderJournalHasNone() {
        let journal = RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "journal-\(UUID().uuidString).jsonl"))
        defer { journal.clear() }
        let points = track(seconds: 5)
        journal.begin(start: points[0].time)
        for p in points { journal.append(p) }
        #expect(journal.load()?.id == nil)
    }

    @MainActor
    @Test func aRecordingSavesUnderTheIDItsLivePostsCarried() throws {
        let journal = RideJournal(url: FileManager.default.temporaryDirectory.appending(path: "journal-\(UUID().uuidString).jsonl"))
        defer { journal.clear() }
        let recorder = PhoneRideRecorder(journal: journal, choices: RecordChoices(defaults: tempDefaults()))
        recorder.choose(sport: .strength)          // a timer: no GPS needed to start
        recorder.start()
        let id = try #require(recorder.recordingID)
        #expect(journal.load() == nil || journal.load()?.id == id)
        #expect(recorder.liveInterval == 15)
        recorder.sharingEvery = 5
        #expect(recorder.liveInterval == 5)
        var ended: UUID?
        recorder.onRecordingEnded = { ended = $0 }
        recorder.discard()
        #expect(ended == id)
        #expect(recorder.recordingID == nil)
        #expect(recorder.sharingEvery == nil)
        #expect(recorder.liveInterval == 15)
    }
}
