import SwiftUI

/// Every activity on the server, of every sport, newest first (GET /api/v1/rides, a page at a time), with a sport filter and search.
/// A list beside the chosen activity when there's room (a phone on its side, the iPhone Duo's inner screen); one above the other otherwise.
/// The selection lives here, so folding or unfolding the Duo keeps the activity that's open.
struct ActivitiesView: View {
    @Environment(Session.self) private var session
    @State private var items: [ActivityItem] = []
    @State private var total = 0
    @State private var error: AppError?
    @State private var loading = false
    @State private var query = ""
    @State private var group = ""
    @State private var selection: ActivityItem?

    private static let pageSize = 30

    var body: some View {
        NavigationSplitView {
            list
                .navigationTitle("Activities")
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Picker("Sport", selection: $group) {
                                Text("Every sport").tag("")
                                Label("Rides", systemImage: "bicycle").tag("ride")
                                Label("On foot", systemImage: "figure.run").tag("foot")
                                Label("Swims", systemImage: "figure.pool.swim").tag("swim")
                                ForEach(["Strength", "HIIT", "Yoga"], id: \.self) { Label($0, systemImage: ActivitySport.systemImage($0)).tag($0) }
                            }
                        } label: {
                            Label("Sport", systemImage: group.isEmpty ? "line.3.horizontal.decrease.circle" : "line.3.horizontal.decrease.circle.fill")
                        }
                    }
                }
        } detail: {
            if let selection {
                ActivityDetailView(item: selection) { deleted in
                    items.removeAll { $0.id == deleted }
                    total = max(0, total - 1)
                    self.selection = nil
                }
                .id(selection.id)
            } else {
                ContentUnavailableView("Choose an activity", systemImage: "list.bullet.rectangle",
                                       description: Text("Pick a ride, run, swim or session to see it here."))
            }
        }
        .searchable(text: $query, prompt: "Name or place")
        .task(id: "\(group)|\(query)") {
            // Typing: wait for a pause before asking the server.
            if !query.isEmpty { try? await Task.sleep(for: .milliseconds(350)) }
            guard !Task.isCancelled else { return }
            await load(reset: true)
        }
    }

    private var list: some View {
        List(selection: $selection) {
            if let error, items.isEmpty {
                ContentUnavailableView {
                    Label("Couldn't reach Headwind", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(error.localizedDescription)
                } actions: {
                    Button("Try again") { Task { await load(reset: true) } }
                }
            } else if items.isEmpty && !loading {
                ContentUnavailableView(query.isEmpty ? "No activities yet" : "Nothing found", systemImage: "figure.mixed.cardio")
            }
            ForEach(items) { item in
                NavigationLink(value: item) { ActivityRow(item: item, units: session.units) }
                    .onAppear {
                        if item.id == items.last?.id, items.count < total { Task { await load(reset: false) } }
                    }
            }
            if loading { ProgressView().frame(maxWidth: .infinity) }
        }
        .refreshable { await load(reset: true) }
    }

    private func load(reset: Bool) async {
        guard !loading || reset else { return }
        loading = true
        defer { loading = false }
        var q = [URLQueryItem(name: "offset", value: String(reset ? 0 : items.count)), URLQueryItem(name: "limit", value: String(Self.pageSize))]
        if !group.isEmpty { q.append(URLQueryItem(name: "group", value: group)) }
        if !query.isEmpty { q.append(URLQueryItem(name: "q", value: query)) }
        do throws(AppError) {
            let page = try await session.load("rides", query: q, as: ActivityPage.self)
            if reset { items = page.items } else { items += page.items.filter { new in !items.contains { $0.id == new.id } } }
            total = page.total
            error = nil
        } catch {
            self.error = error
        }
    }
}

private struct ActivityRow: View {
    var item: ActivityItem
    var units: Units

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: ActivitySport.systemImage(item.sport))
                .font(.title3)
                .foregroundStyle(Color.accentColor)
                .frame(width: 30)
                .accessibilityLabel(item.label ?? item.sport ?? "Activity")
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title).font(.headline).lineLimit(1)
                Text(details.joined(separator: " · "))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            Text(ActivityDates.short(item.date))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    private var details: [String] {
        let sport = Sport(rawValue: item.sport ?? "")
        var parts: [String] = []
        if let d = item.distanceM, d > 0 { parts.append(sport.map { units.distance(metres: d, sport: $0) } ?? units.distance(metres: d)) }
        if let t = item.movingS, t > 0 { parts.append(Units.duration(seconds: t)) }
        if item.group == "ride" || item.group == "foot", let e = item.elevM, e > 0 { parts.append(units.elevation(metres: e)) }
        return parts
    }
}

/// The server's local start times ("2026-10-20T18:30:00", no zone: the wall-clock time where it happened), read as such.
enum ActivityDates {
    static func parse(_ s: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: String(s.prefix(19)))
    }

    static func short(_ s: String) -> String {
        guard let d = parse(s) else { return String(s.prefix(10)) }
        return d.formatted(.dateTime.day().month(.abbreviated).year(.twoDigits))
    }

    static func long(_ s: String?) -> String {
        guard let s, let d = parse(s) else { return "" }
        return d.formatted(date: .complete, time: .shortened)
    }
}
