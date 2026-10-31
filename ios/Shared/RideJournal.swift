import Foundation

/// Appends every kept fix to a file as the ride records, so a crash, a dead battery or iOS killing the app
/// doesn't lose the ride. On the next launch the recorder finds the journal and offers to save what was there.
///
/// A timed-only session (strength, a pool swim) has no fixes, so its journal notes the time now and then instead, and what the Watch measured.
/// On the phone with Bluetooth sensors, a timed session also journals a sample of their readings every second.
///
/// Format: JSON Lines, one event per line: {"start":…,"sport":"Run","bike":3}, {"p":{point}}, {"seg":true} (a resume after pause),
/// {"tick":…,"active":…,"dist":…,"kcal":…,"hr":…} (a timed session's progress: the time, the active seconds so far, and the Watch's figures),
/// {"s":{"t":…,"hr":…,"w":…,"cad":…,"v":…,"d":…}} (a timed session's sensor sample).
struct RideJournal {
    /// What a journal holds after a crash. A journal from before the sport was chosen has none: it's a ride.
    struct Recovered: Equatable {
        var start: Date
        var sport: Sport = .ride
        var bikeId: Int?
        var segments: [[RidePoint]]
        /// A timed-only session's last progress note.
        var session: SessionProgress?
        /// A timed session's sensor samples, from the phone.
        var samples: [SessionSample] = []
    }

    /// How far a timed-only session had got.
    struct SessionProgress: Codable, Equatable, Sendable {
        var at: Date
        var active: TimeInterval
        var distance: Double?
        var calories: Double?
        var heartRate: Int?
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
        var tick: SessionProgress?
        var s: SessionSample?
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

    func note(_ progress: SessionProgress) { write(Event(tick: progress)) }

    func append(_ sample: SessionSample) { write(Event(s: sample)) }

    func clear() { try? FileManager.default.removeItem(at: url) }

    /// The recorded ride, or nil if there's no journal or it has fewer than two fixes: one point isn't a track, and the server
    /// would refuse it (422) on every retry. A timed-only session needs a progress note at least a minute in instead.
    func load() -> Recovered? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        var head = Event()
        var segments: [[RidePoint]] = [[]]
        var progress: SessionProgress?
        var samples: [SessionSample] = []
        for line in data.split(separator: UInt8(ascii: "\n")) {
            // A crash mid-write can leave a truncated last line; skip anything that doesn't parse.
            guard let event = try? Self.decoder.decode(Event.self, from: Data(line)) else { continue }
            if event.start != nil { head = event }
            if let p = event.p { segments[segments.count - 1].append(p) }
            if event.seg == true, !(segments.last?.isEmpty ?? true) { segments.append([]) }
            if let tick = event.tick { progress = tick }
            if let sample = event.s { samples.append(sample) }
        }
        segments.removeAll { $0.isEmpty }
        let sport = Sport(stored: head.sport)
        if !sport.usesGPS {
            guard let start = head.start, let progress, progress.active >= RideSummary.minimumSession else { return nil }
            return Recovered(start: start, sport: sport, bikeId: head.bike, segments: [], session: progress, samples: samples)
        }
        guard let first = segments.first?.first, segments.joined().count >= 2 else { return nil }
        return Recovered(start: head.start ?? first.time, sport: sport, bikeId: head.bike, segments: segments)
    }

    /// The summary of a recovered ride or session, ready to save.
    static func summary(of r: Recovered) -> RideSummary {
        if let s = r.session {
            guard r.samples.isEmpty else {
                // The phone's sensors: their averages, and the distance as far as the last sample.
                let track = SessionTrack(samples: r.samples)
                var summary = RideSummary.session(start: r.start, elapsed: s.active, sport: r.sport, track: track, bikeId: r.bikeId)
                summary.distance = max(summary.distance, s.distance ?? 0)
                return summary
            }
            return .session(start: r.start, elapsed: s.active, sport: r.sport, distance: s.distance ?? 0, averageHeartRate: s.heartRate,
                            calories: s.calories, bikeId: r.bikeId)
        }
        let t = RideTracker(segments: r.segments)
        let end = t.lastPoint?.time ?? r.start
        return RideSummary(start: r.start, tracker: t, elapsed: end.timeIntervalSince(r.start), sport: r.sport, bikeId: r.bikeId)
    }

    private func write(_ event: Event) {
        guard var line = try? Self.encoder.encode(event), let handle = try? FileHandle(forWritingTo: url) else { return }
        line.append(UInt8(ascii: "\n"))
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: line)
    }
}
