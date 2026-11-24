import CoreLocation
import Foundation

/// The track so far, thinned for drawing on a map while recording (the Watch's map page). Only for the screen: the recording itself, its
/// journal and its GPX keep every fix (RideTracker), so nothing here changes what's saved or uploaded.
///
/// Thinned as the fixes arrive, so a redraw costs the same an hour in as a minute in: a fix is kept only when the line from the last kept
/// one would otherwise stray more than `tolerance` metres from a fix in between, so a straight road is two points and a bend keeps its
/// corners. Past `maxPoints` the tolerance doubles and what's kept is thinned again, so a long day stays a few thousand points at most.
/// The newest fix always ends the last line, so the line reaches the rider. Each stretch between pauses is a line of its own, as the
/// GPX's segments are, so the gap isn't drawn.
struct MapTrack: Equatable, Sendable {
    struct Coordinate: Equatable, Sendable {
        var lat: Double
        var lon: Double

        var location: CLLocationCoordinate2D { CLLocationCoordinate2D(latitude: lat, longitude: lon) }
    }

    /// Metres a fix in between may stray from the drawn line. A few metres is below what a Watch screen shows at any useful zoom.
    static let startTolerance = 3.0
    /// Kept points, all lines together, before the tolerance doubles.
    static let maxPoints = 2000
    /// Fixes waiting since the last kept one, at most: a long straight still commits a point now and then, which bounds each fix's work.
    static let maxPending = 120

    private(set) var tolerance = startTolerance
    /// Kept points, one array per stretch between pauses.
    private(set) var segments: [[Coordinate]] = []
    /// Fixes since the last kept one, the newest last; every one lies within `tolerance` of the line from the last kept point to the newest.
    private var pending: [Coordinate] = []
    private var startsSegment = true

    init() {}

    var pointCount: Int { segments.reduce(0) { $0 + $1.count } }

    /// The newest fix, where the rider is.
    var latest: Coordinate? { pending.last ?? segments.last?.last }

    /// What to draw: the kept points, the last line reaching to the newest fix. Lines of a single point are left out.
    var lines: [[Coordinate]] {
        var out = segments
        if let newest = pending.last, !out.isEmpty { out[out.count - 1].append(newest) }
        return out.filter { $0.count >= 2 }
    }

    mutating func add(_ point: RidePoint) {
        add(Coordinate(lat: point.lat, lon: point.lon))
    }

    mutating func add(_ c: Coordinate) {
        if startsSegment {
            segments.append([c])
            pending = []
            startsSegment = false
            return
        }
        let committed = Self.step(c, kept: &segments[segments.count - 1], pending: &pending, tolerance: tolerance)
        if committed, pointCount > Self.maxPoints { coarsen() }
    }

    /// After a pause: the next fix starts a new line. The stretch before ends at its last fix.
    mutating func newSegment() {
        if let last = pending.last, !segments.isEmpty { segments[segments.count - 1].append(last) }
        pending = []
        startsSegment = true
    }

    /// Doubles the tolerance until what's kept fits again.
    private mutating func coarsen() {
        while pointCount > Self.maxPoints {
            tolerance *= 2
            segments = segments.map { Self.simplify($0, tolerance: tolerance) }
        }
    }

    /// One fix into a line: either it extends the pending run, or the fix before it is kept and it starts a new run. Returns whether a
    /// point was kept.
    private static func step(_ c: Coordinate, kept: inout [Coordinate], pending: inout [Coordinate], tolerance: Double) -> Bool {
        guard let anchor = kept.last else {
            kept.append(c)
            return true
        }
        if pending.count < maxPending, pending.allSatisfy({ distance(from: $0, toSegment: anchor, c) <= tolerance }) {
            pending.append(c)
            return false
        }
        if let previous = pending.last { kept.append(previous) }
        pending = [c]
        // The run just kept may have been long and straight; the new one starts from its end, so `c` alone is within tolerance.
        return true
    }

    /// The same thinning over a whole line, keeping its first and last points.
    static func simplify(_ points: [Coordinate], tolerance: Double) -> [Coordinate] {
        guard points.count > 2 else { return points }
        var kept: [Coordinate] = []
        var pending: [Coordinate] = []
        for p in points { _ = step(p, kept: &kept, pending: &pending, tolerance: tolerance) }
        if let last = pending.last { kept.append(last) }
        return kept
    }

    /// Metres from `p` to the segment a–b, on a flat projection about `a` (plenty for the few hundred metres between kept points).
    static func distance(from p: Coordinate, toSegment a: Coordinate, _ b: Coordinate) -> Double {
        let metresPerDegree = 111_195.0
        let k = cos(a.lat * .pi / 180)
        let bx = (b.lon - a.lon) * k * metresPerDegree, by = (b.lat - a.lat) * metresPerDegree
        let px = (p.lon - a.lon) * k * metresPerDegree, py = (p.lat - a.lat) * metresPerDegree
        let length2 = bx * bx + by * by
        let t = length2 > 0 ? max(0, min(1, (px * bx + py * by) / length2)) : 0
        let dx = px - t * bx, dy = py - t * by
        return (dx * dx + dy * dy).squareRoot()
    }
}
