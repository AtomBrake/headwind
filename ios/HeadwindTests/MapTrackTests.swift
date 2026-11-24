import Foundation
import Testing
@testable import Headwind

/// The Watch map page's thinned track (Shared/MapTrack.swift).
struct MapTrackTests {
    private static let metresPerDegree = 111_195.0

    /// A point `north` and `east` metres from a start near Bristol.
    private func at(north: Double, east: Double) -> MapTrack.Coordinate {
        let lat0 = 51.45
        return .init(lat: lat0 + north / Self.metresPerDegree,
                     lon: -2.59 + east / (Self.metresPerDegree * cos(lat0 * .pi / 180)))
    }

    private func track(_ points: [MapTrack.Coordinate]) -> MapTrack {
        var t = MapTrack()
        points.forEach { t.add($0) }
        return t
    }

    @Test func aStraightRoadIsItsEnds() {
        let points = (0...1000).map { at(north: Double($0) * 5, east: 0) }
        let t = track(points)
        let lines = t.lines
        #expect(lines.count == 1)
        #expect(lines[0].first == points.first)
        #expect(lines[0].last == points.last)
        // A long straight still keeps a point every `maxPending` fixes, but nothing like all 1001.
        #expect(lines[0].count <= 1001 / MapTrack.maxPending + 3)
    }

    @Test func cornersAreKept() {
        // A 200 m square, a fix every 5 m.
        var points: [MapTrack.Coordinate] = []
        for i in 0..<40 { points.append(at(north: Double(i) * 5, east: 0)) }
        for i in 0..<40 { points.append(at(north: 200, east: Double(i) * 5)) }
        for i in 0..<40 { points.append(at(north: 200 - Double(i) * 5, east: 200)) }
        for i in 0...40 { points.append(at(north: 0, east: 200 - Double(i) * 5)) }
        let line = track(points).lines[0]
        for corner in [at(north: 200, east: 0), at(north: 200, east: 200), at(north: 0, east: 200)] {
            let nearest = line.map { MapTrack.distance(from: corner, toSegment: $0, $0) }.min() ?? .infinity
            #expect(nearest <= 5.1, "corner \(corner) not kept")
        }
        #expect(line.count < 12)
    }

    @Test func anOutAndBackKeepsItsTurn() {
        let out = (0...100).map { at(north: Double($0) * 5, east: 0) }
        let back = (0...60).map { at(north: 500 - Double($0) * 5, east: 0.5) }
        let line = track(out + back).lines[0]
        let furthest = line.map { ($0.lat - out[0].lat) * Self.metresPerDegree }.max() ?? 0
        #expect(furthest >= 495)
        #expect(line.last == back.last)
    }

    @Test func everyFixIsNearTheLine() {
        // A wiggly road: every fix should be within the tolerance of what's drawn.
        let points = (0...600).map { i in at(north: Double(i) * 4, east: 30 * sin(Double(i) / 15)) }
        let t = track(points)
        let line = t.lines[0]
        for p in points {
            let nearest = zip(line, line.dropFirst()).map { MapTrack.distance(from: p, toSegment: $0, $1) }.min() ?? .infinity
            #expect(nearest <= t.tolerance + 0.01)
        }
        #expect(line.count < points.count / 2)
    }

    @Test func theNewestFixEndsTheLine() {
        var t = track((0...10).map { at(north: Double($0) * 5, east: 0) })
        let newest = at(north: 53, east: 0)
        t.add(newest)
        #expect(t.lines.last?.last == newest)
        #expect(t.latest == newest)
    }

    @Test func pausesSplitTheLines() {
        var t = track((0...20).map { at(north: Double($0) * 5, east: 0) })
        t.newSegment()
        t.newSegment()   // twice, as a pause straight after a resume can: still one new line
        (0...20).forEach { t.add(at(north: 100, east: 50 + Double($0) * 5)) }
        let lines = t.lines
        #expect(lines.count == 2)
        #expect(lines[0].last == at(north: 100, east: 0))   // the stretch before the pause ends where it ended
        #expect(lines[1].first == at(north: 100, east: 50))
    }

    @Test func aSingleFixDrawsNothing() {
        var t = MapTrack()
        #expect(t.lines.isEmpty)
        t.add(at(north: 0, east: 0))
        #expect(t.lines.isEmpty)
        #expect(t.latest != nil)
    }

    @Test func aLongDayStaysUnderTheCap() {
        // Six hours at a fix a second, never straight for long: far more than maxPoints survive the first tolerance.
        var t = MapTrack()
        for i in 0..<21_600 {
            let s = Double(i)
            t.add(at(north: s * 4, east: 60 * sin(s / 8) + 25 * sin(s / 3.1)))
        }
        #expect(t.pointCount <= MapTrack.maxPoints)
        #expect(t.tolerance > MapTrack.startTolerance)
        #expect(t.lines[0].first == at(north: 0, east: 0))
    }
}
