import Foundation

/// Appends every kept fix to a file as the ride records, so a crash, a dead battery or iOS killing the app
/// doesn't lose the ride. On the next launch the recorder finds the journal and offers to save what was there.
///
/// Format: JSON Lines, one event per line: {"start":…,"sport":"Run","bike":3}, {"p":{point}}, {"seg":true} (a resume after pause).
struct RideJournal {
    /// What a journal holds after a crash. A journal from before the sport was chosen has none: it's a ride.
    struct Recovered: Equatable {
        var start: Date
        var sport: Sport = .ride
        var bikeId: Int?
        var segments: [[RidePoint]]
    }

    let url: URL

    static var standard: RideJournal {
        let dir = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        return RideJournal(url: dir.appending(path: "ride-in-progress.jsonl"))
    }

    private struct Event: Codable {
        var start: Date?
        var sport: String?
        var bike: Int?
        var p: RidePoint?
        var seg: Bool?
    }

    private static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .millisecondsSince1970
        return e
    }()

    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .millisecondsSince1970
        return d
    }()

    var exists: Bool { FileManager.default.fileExists(atPath: url.path()) }

    func begin(start: Date, sport: Sport = .ride, bikeId: Int? = nil) {
        try? FileManager.default.removeItem(at: url)
        FileManager.default.createFile(atPath: url.path(), contents: nil)
        write(Event(start: start, sport: sport.rawValue, bike: bikeId))
    }

    func append(_ point: RidePoint) { write(Event(p: point)) }

    func newSegment() { write(Event(seg: true)) }

    func clear() { try? FileManager.default.removeItem(at: url) }

    /// The recorded ride, or nil if there's no journal or it has fewer than two fixes: one point isn't a track, and the server
    /// would refuse it (422) on every retry.
    func load() -> Recovered? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        var head = Event()
        var segments: [[RidePoint]] = [[]]
        for line in data.split(separator: UInt8(ascii: "\n")) {
            // A crash mid-write can leave a truncated last line; skip anything that doesn't parse.
            guard let event = try? Self.decoder.decode(Event.self, from: Data(line)) else { continue }
            if event.start != nil { head = event }
            if let p = event.p { segments[segments.count - 1].append(p) }
            if event.seg == true, !(segments.last?.isEmpty ?? true) { segments.append([]) }
        }
        segments.removeAll { $0.isEmpty }
        guard let first = segments.first?.first, segments.joined().count >= 2 else { return nil }
        return Recovered(start: head.start ?? first.time, sport: Sport(stored: head.sport), bikeId: head.bike, segments: segments)
    }

    private func write(_ event: Event) {
        guard var line = try? Self.encoder.encode(event), let handle = try? FileHandle(forWritingTo: url) else { return }
        line.append(UInt8(ascii: "\n"))
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: line)
    }
}
