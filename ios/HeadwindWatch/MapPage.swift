import MapKit
import SwiftUI

/// The recording's third page, for a sport with GPS: the track so far and where you are, the map following you and turned to the way
/// you're going, the Digital Crown zooming. Two figures over it so it stands on its own.
///
/// The page moves the camera itself, to each new fix at the zoom the crown left, rather than using MapKit's follow mode: that puts the zoom
/// back to its own each time it starts following again, which would be every time the wrist comes up. It turns to the direction of travel
/// from GPS rather than the compass, which is steadier on a bike or a swinging arm and needs no compass running; stopped, it keeps the
/// last direction.
///
/// With the wrist down, in Always On, or on another page it rests: dimmed, the camera left where it was and the track as it was, so no
/// fix redraws the map. It catches up when the wrist comes up.
///
/// Without tiles (no phone, no connection) MapKit still draws the lines and your position over its empty grid.
struct MapPage: View {
    @Environment(WorkoutManager.self) private var workout
    @Environment(\.isLuminanceReduced) private var luminanceReduced
    @Environment(\.scenePhase) private var scenePhase
    /// Whether this is the page on screen: the TabView keeps the others alive.
    var showing: Bool

    /// Until the first fix, wherever the Watch is.
    @State private var position = MapCameraPosition.userLocation(fallback: .automatic)
    /// Metres from the camera to the ground: the crown's zoom, kept while the page rests. About 400 m across the screen to start.
    @State private var distance = 900.0
    /// The track as it was when the page came to rest; drawn instead of the live one until it wakes.
    @State private var frozen = MapTrack()

    private var resting: Bool { luminanceReduced || scenePhase != .active || !showing }

    var body: some View {
        // Read the live track only while awake, so a resting page isn't redrawn with each fix.
        let track = resting ? frozen : workout.mapTrack
        ZStack {
            Map(position: $position, interactionModes: resting ? [] : [.zoom]) {
                // Layers, bottom first. A route being followed goes in under the track.
                TrackLines(lines: track.lines, color: .accentColor)
                UserAnnotation()
            }
            .mapStyle(.standard(emphasis: .muted, pointsOfInterest: .excludingAll))
            .mapControls {}
            .onMapCameraChange(frequency: .continuous) { context in
                if !resting { distance = context.camera.distance }
            }
            .ignoresSafeArea()

            if resting {
                Color.black.opacity(0.45)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)
            }
        }
        .overlay(alignment: .bottom) { MapFigures() }
        .onChange(of: track.latest) { follow() }
        .onChange(of: resting, initial: true) { _, rest in
            if rest {
                frozen = workout.mapTrack
            } else {
                follow(animated: false)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("watch-map-page")
    }

    /// Centre on the newest fix, at the crown's zoom, turned to the way you're going.
    private func follow(animated: Bool = true) {
        guard !resting, let here = workout.mapTrack.latest else { return }
        let camera = MapCamera(centerCoordinate: here.location, distance: distance, heading: workout.course ?? 0, pitch: 0)
        if animated {
            withAnimation(.easeInOut(duration: 0.5)) { position = .camera(camera) }
        } else {
            position = .camera(camera)
        }
    }
}

/// Lines on the map, one per stretch between pauses. The track uses it; a route being followed can be another, drawn beneath.
struct TrackLines: MapContent {
    let lines: [[MapTrack.Coordinate]]
    var color: Color
    var width: CGFloat = 4

    var body: some MapContent {
        ForEach(lines.indices, id: \.self) { i in
            MapPolyline(coordinates: lines[i].map(\.location))
                .stroke(color, style: StrokeStyle(lineWidth: width, lineCap: .round, lineJoin: .round))
        }
    }
}

/// Distance and time over the map; on foot, distance and pace.
private struct MapFigures: View {
    @Environment(WorkoutManager.self) private var workout
    @Environment(PhoneLink.self) private var phone

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let sport = workout.sport
            HStack(spacing: 8) {
                Text(phone.units.distance(metres: workout.tracker.distance, sport: sport))
                    .accessibilityIdentifier("watch-map-distance")
                Spacer(minLength: 0)
                if sport.isOnFoot {
                    Text(phone.units.rate(metresPerSecond: workout.tracker.currentSpeed, sport: sport))
                } else {
                    Text(Units.clock(seconds: workout.clock.elapsed(at: context.date)))
                        .foregroundStyle(workout.state == .paused ? .yellow : .primary)
                }
            }
            .font(.system(.body, design: .rounded).weight(.semibold).monospacedDigit())
            .lineLimit(1)
            .minimumScaleFactor(0.7)
            .padding(.horizontal, 10)
            .padding(.vertical, 3)
            .background(.black.opacity(0.6), in: Capsule())
            .padding(.horizontal, 8)
        }
    }
}
