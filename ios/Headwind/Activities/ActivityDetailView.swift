import Charts
import MapKit
import PhotosUI
import SwiftUI

/// One activity from the server (GET /api/v1/rides/<kind>/<id>): its map, the numbers that suit its sport, its charts and its photos.
/// Photos are added from the library with PhotosPicker, which needs no photo-library permission: only the pictures picked are shared.
struct ActivityDetailView: View {
    var item: ActivityItem
    var onDelete: (String) -> Void
    @Environment(Session.self) private var session
    @State private var detail: ActivityDetail?
    @State private var error: AppError?
    @State private var picked: [PhotosPickerItem] = []
    @State private var adding = 0
    @State private var actionError: AppError?
    @State private var confirmDelete = false
    @State private var viewing: ActivityDetail.Photo?

    var body: some View {
        Loaded(value: detail, error: error, retry: load) { d in
            ScrollView {
                VStack(spacing: 16) {
                    if let track = d.track, track.count > 1 {
                        TrackMap(track: track)
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
                        PhotosCard(photos: d.photos ?? [], adding: adding, picked: $picked, viewing: $viewing, delete: delete)
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
        .sheet(item: $viewing) { photo in
            NavigationStack {
                AuthedImage(path: photo.url, contentMode: .fit)
                    .navigationTitle(photo.caption ?? "Photo")
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { viewing = nil } } }
            }
        }
        .onChange(of: picked) { _, items in
            guard !items.isEmpty else { return }
            picked = []
            Task { await add(items) }
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

    /// Each picked picture as a shrunk JPEG, one request each, then the activity again for its photos.
    private func add(_ items: [PhotosPickerItem]) async {
        adding += items.count
        for choice in items {
            defer { adding = max(0, adding - 1) }
            guard let raw = try? await choice.loadTransferable(type: Data.self), let jpeg = PhotoPrep.jpeg(from: raw) else {
                actionError = .validationError(message: "That picture couldn't be read.")
                continue
            }
            do throws(AppError) {
                _ = try await session.call { client async throws(AppError) in
                    try await client.upload("rides/\(item.kind)/\(item.id)/photos", file: jpeg, filename: "photo.jpg", mimeType: "image/jpeg",
                                            fields: ["client_id": choice.itemIdentifier ?? UUID().uuidString], as: Ignored.self)
                }
            } catch {
                actionError = error
            }
        }
        await load()
    }

    private func delete(_ photo: ActivityDetail.Photo) {
        Task {
            do throws(AppError) {
                _ = try await session.call { client async throws(AppError) in
                    try await client.delete("rides/\(item.kind)/\(item.id)/photos/\(photo.id)", as: Ignored.self)
                }
                await load()
            } catch {
                actionError = error
            }
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

private struct PhotosCard: View {
    var photos: [ActivityDetail.Photo]
    var adding: Int
    @Binding var picked: [PhotosPickerItem]
    @Binding var viewing: ActivityDetail.Photo?
    var delete: (ActivityDetail.Photo) -> Void

    var body: some View {
        Card(title: "Photos") {
            if photos.isEmpty && adding == 0 {
                Text("No photos yet.").foregroundStyle(.secondary)
            }
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 90), spacing: 6)], spacing: 6) {
                ForEach(photos) { photo in
                    Button { viewing = photo } label: {
                        AuthedImage(path: photo.thumbUrl)
                            .frame(minWidth: 90, minHeight: 90)
                            .frame(maxWidth: .infinity)
                            .aspectRatio(1, contentMode: .fit)
                            .clipped()
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    .buttonStyle(.plain)
                    .contextMenu {
                        Button("Delete photo", systemImage: "trash", role: .destructive) { delete(photo) }
                    }
                    .accessibilityLabel(photo.caption ?? "Photo")
                }
                ForEach(0..<adding, id: \.self) { _ in
                    ProgressView().frame(width: 90, height: 90)
                }
            }
            PhotosPicker(selection: $picked, maxSelectionCount: 10, matching: .images, photoLibrary: .shared()) {
                Label("Add photos", systemImage: "photo.badge.plus")
            }
        }
    }
}
