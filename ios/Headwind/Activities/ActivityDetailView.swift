import Charts
import MapKit
import SwiftUI

/// One activity from the server (GET /api/v1/rides/<kind>/<id>): its map (a Zwift world's for a virtual ride), the numbers that suit its sport, its charts and its photos
/// (PhotosCard, which adds, deletes, orders and captions them).
struct ActivityDetailView: View {
    var item: ActivityItem
    var onDelete: (String) -> Void
    @Environment(Session.self) private var session
    @State private var detail: ActivityDetail?
    @State private var error: AppError?
    @State private var actionError: AppError?
    @State private var confirmDelete = false

    var body: some View {
        Loaded(value: detail, error: error, retry: load) { d in
            ScrollView {
                VStack(spacing: 16) {
                    if let track = d.track, track.count > 1 {
                        Group {
                            if let world = d.zwiftWorld { ZwiftTrackMap(track: track, world: world) } else { TrackMap(track: track) }
                        }
                            .frame(height: 260)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    CardColumns {
                        Card(title: d.label ?? d.sport) {
                            StatsGrid(detail: d, units: session.units)
                        }
                        if let w = d.weather, w.summary != nil || w.tempC != nil {
                            Card(title: "Weather") {
                                Text([w.summary, w.tempC.map { session.units.metric ? "\(Units.whole($0)) °C" : "\(Units.whole($0 * 9 / 5 + 32)) °F" },
                                      w.windKph.map { session.units.metric ? "wind \(Units.whole($0)) km/h" : "wind \(Units.whole($0 / 1.609)) mph" }]
                                    .compactMap { $0 }.joined(separator: " · "))
                            }
                        }
                        ForEach(charts(d), id: \.title) { chart in
                            Card(title: chart.title) { SeriesChart(points: chart.points, tint: chart.tint) }
                        }
                        PhotosCard(path: "rides/\(item.kind)/\(item.id)/photos",
                                   photos: Binding(get: { detail?.photos ?? [] }, set: { detail?.photos = $0 }))
                        if let notes = [d.description, d.notes].compactMap({ $0?.isEmpty == false ? $0 : nil }).first {
                            Card(title: "Notes") { Text(notes) }
                        }
                    }
                }
                .padding(16)
            }
            .background(Color(.systemGroupedBackground))
            .refreshable { await load() }
        }
        .navigationTitle(detail?.name ?? item.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    if let server = session.pairing?.server {
                        Link(destination: server.appending(path: "rides/\(item.id)")) { Label("Open in Safari", systemImage: "safari") }
                    }
                    Button("Delete", systemImage: "trash", role: .destructive) { confirmDelete = true }
                } label: {
                    Label("More", systemImage: "ellipsis.circle")
                }
            }
        }
        .safeAreaInset(edge: .top) {
            Text(ActivityDates.long(detail?.date ?? item.date) + (detail?.city.map { " · \($0)" } ?? ""))
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
                .background(.bar)
        }
        .confirmationDialog("Delete this activity from Headwind?", isPresented: $confirmDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { Task { await deleteActivity() } }
        } message: {
            Text("It's removed from the server for good, and a Garmin sync won't bring it back.")
        }
        .alert("Something went wrong", isPresented: Binding(get: { actionError != nil }, set: { if !$0 { actionError = nil } }),
               presenting: actionError) { _ in
            Button("OK", role: .cancel) {}
        } message: { e in
            Text(e.localizedDescription)
        }
        .task { await load() }
    }

    private struct ChartSpec {
        var title: String
        var points: [ActivityDetail.Point]
        var tint: Color
    }

    private func charts(_ d: ActivityDetail) -> [ChartSpec] {
        var out: [ChartSpec] = []
        let units = session.units
        if let e = d.series?.elevation, !e.isEmpty {
            out.append(ChartSpec(title: "Elevation · \(units.metric ? "m" : "ft")",
                                 points: e.map { .init(d: $0.d, v: units.metric ? $0.v : $0.v * 3.28084) }, tint: .green))
        }
        if let s = d.series?.speed, !s.isEmpty, ActivitySport.group(d.sport) == "ride" {
            out.append(ChartSpec(title: "Speed · \(units.metric ? "km/h" : "mph")",
                                 points: s.map { .init(d: $0.d, v: $0.v * (units.metric ? 3.6 : 2.236936)) }, tint: .blue))
        }
        if let h = d.series?.heartrate, !h.isEmpty { out.append(ChartSpec(title: "Heart rate · bpm", points: h, tint: .red)) }
        if let w = d.series?.watts, !w.isEmpty { out.append(ChartSpec(title: "Power · W", points: w, tint: .orange)) }
        return out
    }

    private func load() async {
        do throws(AppError) {
            detail = try await session.load("rides/\(item.kind)/\(item.id)", as: ActivityDetail.self)
            error = nil
        } catch {
            self.error = error
        }
    }

    private func deleteActivity() async {
        do throws(AppError) {
            _ = try await session.call { client async throws(AppError) in
                try await client.delete("rides/\(item.kind)/\(item.id)", as: Ignored.self)
            }
            onDelete(item.id)
        } catch {
            actionError = error
        }
    }
}

/// The numbers that suit the sport: distance and speed or pace where there's a distance, climbing on land, power where there was a meter.
private struct StatsGrid: View {
    var detail: ActivityDetail
    var units: Units

    private struct Item: Identifiable {
        var value: String
        var caption: String
        var id: String { caption }
    }

    private var items: [Item] {
        let d = detail
        let sport = Sport(rawValue: d.sport ?? "")
        let group = ActivitySport.group(d.sport)
        var out: [Item] = []
        if let m = d.distanceM, m > 0 {
            out.append(Item(value: sport.map { units.distance(metres: m, sport: $0) } ?? units.distance(metres: m), caption: "Distance"))
        }
        if let t = d.movingS, t > 0 { out.append(Item(value: Units.duration(seconds: t), caption: "Moving time")) }
        if let v = d.avgSpeedMps, v > 0, let m = d.distanceM, m > 0 {
            let style = group == "foot" ? "pace" : group == "swim" ? "swim" : "speed"
            if let rate = units.rate(metresPerSecond: v, style: style) { out.append(Item(value: rate, caption: style == "speed" ? "Avg speed" : "Avg pace")) }
        }
        if (group == "ride" || group == "foot"), let e = d.elevM, e > 0 { out.append(Item(value: units.elevation(metres: e), caption: "Climbing")) }
        if let hr = d.avgHr, hr > 0 { out.append(Item(value: "\(Units.whole(hr)) bpm", caption: "Avg heart rate")) }
        if let w = d.avgWatts, w > 0 { out.append(Item(value: "\(Units.whole(w)) W", caption: "Avg power")) }
        if let c = d.cadence, c > 0 { out.append(Item(value: "\(Units.whole(c)) rpm", caption: "Cadence")) }
        if let k = d.calories, k > 0 { out.append(Item(value: Units.whole(k), caption: "Calories")) }
        if let s = d.steps, s > 0 { out.append(Item(value: Units.whole(s), caption: "Steps")) }
        return out
    }

    var body: some View {
        LazyVGrid(columns: [GridItem(.flexible(), alignment: .leading), GridItem(.flexible(), alignment: .leading)], spacing: 14) {
            ForEach(items) { Stat(value: $0.value, caption: $0.caption) }
        }
    }
}

private struct TrackMap: View {
    var track: [[Double]]

    private var coordinates: [CLLocationCoordinate2D] {
        track.compactMap { $0.count >= 2 ? CLLocationCoordinate2D(latitude: $0[0], longitude: $0[1]) : nil }
    }

    var body: some View {
        Map(initialPosition: .automatic, interactionModes: [.pan, .zoom]) {
            MapPolyline(coordinates: coordinates)
                .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
        }
        .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
    }
}

/// A virtual ride over its Zwift world's map alone, as the web's ride page draws it: no real place around it (Watopia is open sea), the map
/// covering the world's box exactly in Web Mercator (Leaflet's imageOverlay), opened fitted to the track and kept to the world. Pinch to zoom,
/// drag to pan, double-tap to fit the track again. A world with no usable box falls back to the plain map.
private struct ZwiftTrackMap: View {
    var track: [[Double]]
    var world: ActivityDetail.ZwiftWorld
    @State private var zoom: CGFloat = 1
    @State private var center: CGPoint?          // in projected degrees; nil is the track's middle
    @GestureState private var pinch: CGFloat = 1
    @GestureState private var drag: CGSize = .zero

    private static let inset: CGFloat = 20
    private static let maxZoom: CGFloat = 8

    /// Web Mercator in degrees, y growing southwards as the screen's does.
    private static func project(_ lat: Double, _ lng: Double) -> CGPoint {
        CGPoint(x: lng, y: -log(tan(.pi / 4 + lat * .pi / 360)) * 180 / .pi)
    }

    private var worldRect: CGRect? {
        guard world.bounds.count == 2, world.bounds.allSatisfy({ $0.count == 2 }) else { return nil }
        let sw = Self.project(world.bounds[0][0], world.bounds[0][1]), ne = Self.project(world.bounds[1][0], world.bounds[1][1])
        let rect = CGRect(x: sw.x, y: ne.y, width: ne.x - sw.x, height: sw.y - ne.y)
        return rect.width > 0 && rect.height > 0 ? rect : nil
    }

    var body: some View {
        if let worldRect {
            GeometryReader { geo in map(size: geo.size, worldRect: worldRect) }
        } else {
            TrackMap(track: track)
        }
    }

    private func map(size: CGSize, worldRect: CGRect) -> some View {
        let points = track.compactMap { $0.count >= 2 ? Self.project($0[0], $0[1]) : nil }
        let xs = points.map(\.x), ys = points.map(\.y)
        let trackRect = CGRect(x: xs.min() ?? worldRect.minX, y: ys.min() ?? worldRect.minY,
                               width: max((xs.max() ?? worldRect.maxX) - (xs.min() ?? worldRect.minX), 0.002),
                               height: max((ys.max() ?? worldRect.maxY) - (ys.min() ?? worldRect.minY), 0.002))
        let fitTrack = min((size.width - 2 * Self.inset) / trackRect.width, (size.height - 2 * Self.inset) / trackRect.height)
        let fitWorld = min(size.width / worldRect.width, size.height / worldRect.height)
        let minZoom = min(1, fitWorld / fitTrack)
        func clampZoom(_ z: CGFloat) -> CGFloat { min(max(z, minZoom), Self.maxZoom) }
        func clampCenter(_ c: CGPoint) -> CGPoint {
            CGPoint(x: min(max(c.x, worldRect.minX), worldRect.maxX), y: min(max(c.y, worldRect.minY), worldRect.maxY))
        }
        let scale = fitTrack * clampZoom(zoom * pinch)
        let start = center ?? CGPoint(x: trackRect.midX, y: trackRect.midY)
        func dragged(_ by: CGSize) -> CGPoint { clampCenter(CGPoint(x: start.x - by.width / scale, y: start.y - by.height / scale)) }
        let middle = dragged(drag)
        func screen(_ p: CGPoint) -> CGPoint {
            CGPoint(x: size.width / 2 + (p.x - middle.x) * scale, y: size.height / 2 + (p.y - middle.y) * scale)
        }

        return ZStack {
            Color(.secondarySystemBackground)
            AuthedImage(path: world.url, contentMode: nil, maxPixels: 3072)
                .frame(width: worldRect.width * scale, height: worldRect.height * scale)
                .position(screen(CGPoint(x: worldRect.midX, y: worldRect.midY)))
            Path { $0.addLines(points.map(screen)) }
                .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 4, lineCap: .round, lineJoin: .round))
        }
        .frame(width: size.width, height: size.height)
        .clipped()
        .contentShape(Rectangle())
        .gesture(SimultaneousGesture(
            MagnifyGesture()
                .updating($pinch) { value, state, _ in state = value.magnification }
                .onEnded { value in zoom = clampZoom(zoom * value.magnification) },
            DragGesture()
                .updating($drag) { value, state, _ in state = value.translation }
                .onEnded { value in center = dragged(value.translation) }
        ))
        .onTapGesture(count: 2) {
            zoom = 1
            center = nil
        }
        .overlay(alignment: .bottomTrailing) {
            Text([world.name, world.credit].compactMap { $0 }.joined(separator: " · "))
                .font(.caption2)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(.thinMaterial, in: Capsule())
                .padding(6)
        }
    }
}

private struct SeriesChart: View {
    var points: [ActivityDetail.Point]
    var tint: Color

    var body: some View {
        Chart(points) { p in
            AreaMark(x: .value("Distance", p.d), y: .value("Value", p.v))
                .foregroundStyle(tint.opacity(0.18))
            LineMark(x: .value("Distance", p.d), y: .value("Value", p.v))
                .foregroundStyle(tint)
        }
        .chartXAxis(.hidden)
        .frame(height: 140)
    }
}
