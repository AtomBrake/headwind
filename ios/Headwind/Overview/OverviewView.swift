import Charts
import SwiftUI

struct OverviewView: View {
    @Environment(Session.self) private var session
    @State private var overview: Overview?
    @State private var error: AppError?
    @State private var period: Overview.Period = .week

    var body: some View {
        NavigationStack {
            Loaded(value: overview, error: error, retry: load) { overview in
                ScrollView {
                    VStack(spacing: 16) {
                        Picker("Period", selection: $period) {
                            ForEach(Overview.Period.allCases) { Text($0.title).tag($0) }
                        }
                        .pickerStyle(.segmented)

                        CardColumns {
                            if let groups = overview.groups, !groups.isEmpty {
                                ForEach(groups) { group in
                                    GroupCard(group: group, totals: group.totals[period.rawValue], units: session.units)
                                }
                            } else {
                                // An older server: rides, and one line for everything else.
                                TotalsCard(totals: overview.totals(for: period), workouts: overview.workouts?[period.rawValue], units: session.units)
                            }
                            if let recovery = overview.recovery {
                                RecoveryCard(recovery: recovery)
                            }
                        }
                        if let weeks = overview.weeklyAll, let groups = overview.groups, !groups.isEmpty {
                            SportsChart(weeks: weeks, groups: groups, units: session.units)
                        } else {
                            WeeklyChart(weeks: overview.weekly, units: session.units)
                        }
                    }
                    .padding(16)
                }
                .background(Color(.systemGroupedBackground))
                .refreshable { await load() }
            }
            .navigationTitle("Overview")
        }
        .task { await load() }
    }

    private func load() async {
        do throws(AppError) {
            overview = try await session.load("overview")
            error = nil
        } catch {
            self.error = error
        }
    }
}

/// The system image for a stat group: 'ride', 'foot', 'swim', or a sport's own name.
private func groupImage(_ key: String) -> String {
    switch key {
    case "ride": "bicycle"
    case "foot": "figure.run"
    case "swim": "figure.pool.swim"
    default: ActivitySport.systemImage(key)
    }
}

/// One sport group's totals for the period: distance and its average speed or pace only where the group has a distance.
private struct GroupCard: View {
    var group: Overview.SportGroup
    var totals: Overview.GroupTotals?
    var units: Units

    var body: some View {
        let t = totals ?? Overview.GroupTotals(count: 0, distanceM: 0, movingS: 0, elevM: 0, calories: 0)
        let hasDistance = group.hasDistance ?? true
        let swim = group.key == "swim"
        Card {
            Label(group.label, systemImage: groupImage(group.key))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
                GridRow {
                    if hasDistance {
                        Stat(value: swim ? units.distance(metres: t.distanceM, sport: .poolSwim) : units.distance(metres: t.distanceM),
                             caption: "Distance")
                    }
                    Stat(value: "\(t.count)", caption: t.count == 1 ? "Activity" : "Activities")
                }
                GridRow {
                    Stat(value: Units.duration(seconds: t.movingS), caption: "Time")
                    if hasDistance, t.movingS > 0, let rate = units.rate(metresPerSecond: t.distanceM / t.movingS, style: group.style) {
                        Stat(value: rate, caption: group.style == "speed" ? "Avg speed" : "Avg pace")
                    } else {
                        Stat(value: Units.whole(t.calories), caption: "Calories")
                    }
                }
                if group.key == "ride" || group.key == "foot" {
                    GridRow {
                        Stat(value: units.elevation(metres: t.elevM), caption: "Climbing")
                        Stat(value: Units.whole(t.calories), caption: "Calories")
                    }
                }
            }
        }
    }
}

private struct TotalsCard: View {
    var totals: Overview.RideTotals
    var workouts: Overview.WorkoutTotals?
    var units: Units

    var body: some View {
        Card(title: "Riding") {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
                GridRow {
                    Stat(value: units.distance(metres: totals.distanceM), caption: "Distance")
                    Stat(value: "\(totals.rides)", caption: totals.rides == 1 ? "Ride" : "Rides")
                }
                GridRow {
                    Stat(value: units.elevation(metres: totals.elevM), caption: "Climbing")
                    Stat(value: Units.duration(seconds: totals.movingS), caption: "Moving time")
                }
                GridRow {
                    Stat(value: Units.whole(totals.calories), caption: "Calories")
                    if let workouts, workouts.count > 0 {
                        Stat(value: "\(workouts.count) · \(units.distance(metres: workouts.distanceM))", caption: "Other activities")
                    } else {
                        Color.clear.frame(height: 1)
                    }
                }
            }
        }
    }
}

/// The last 12 weeks: one sport group by distance (or time, for one without), or every sport stacked by time, since a swim's metres and a
/// ride's miles don't add up.
private struct SportsChart: View {
    var weeks: [Overview.WeekAll]
    var groups: [Overview.SportGroup]
    var units: Units
    @State private var choice = "all"

    private static let palette: [Color] = [.accentColor, .purple, .cyan, .green, .orange, .pink, .yellow, .gray]

    private var chosen: Overview.SportGroup? { groups.first { $0.key == choice } }
    private var byDistance: Bool { chosen.map { $0.hasDistance ?? true } ?? false }

    private var unitLabel: String {
        if !byDistance { return "hours" }
        if chosen?.key == "swim" { return units.metric ? "m" : "yd" }
        return units.metric ? "km" : "mi"
    }

    private func value(_ w: Overview.GroupWeek, key: String) -> Double {
        guard byDistance else { return w.movingS / 3600 }
        if key == "swim" { return units.metric ? w.distanceM : w.distanceM / 0.9144 }
        return units.metric ? w.distanceM / 1000 : w.distanceM / 1609.344
    }

    private struct Bar: Identifiable {
        var week: String
        var current: Bool
        var label: String
        var value: Double
        var id: String { "\(week)|\(label)" }
    }

    private var bars: [Bar] {
        let keys = chosen.map { [$0.key] } ?? groups.map(\.key)
        return weeks.flatMap { week in
            keys.compactMap { key in
                guard let w = week.by[key] else { return nil }
                return Bar(week: week.label, current: week.current, label: groups.first { $0.key == key }?.label ?? key, value: value(w, key: key))
            }
        }
    }

    private var labelled: Set<String> {
        Set(weeks.reversed().enumerated().filter { $0.offset % 3 == 0 }.map(\.element.label))
    }

    var body: some View {
        Card {
            HStack {
                Text("Last 12 weeks · \(unitLabel)")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Picker("Sport", selection: $choice) {
                    Text("Every sport").tag("all")
                    ForEach(groups) { Text($0.label).tag($0.key) }
                }
                .pickerStyle(.menu)
            }
            Chart(bars) { bar in
                BarMark(x: .value("Week", bar.week), y: .value(byDistance ? "Distance" : "Time", bar.value))
                    .foregroundStyle(by: .value("Sport", bar.label))
                    .opacity(bar.current ? 1 : 0.6)
                    .cornerRadius(3)
            }
            .chartForegroundStyleScale(domain: groups.map(\.label), range: groups.indices.map { Self.palette[$0 % Self.palette.count] })
            .chartLegend(chosen == nil && groups.count > 1 ? .visible : .hidden)
            .chartXAxis {
                // Every third week, counted back from this one: twelve "27 Jul"s don't fit across a phone.
                AxisMarks { value in
                    if let label = value.as(String.self), labelled.contains(label) {
                        AxisValueLabel(collisionResolution: .disabled)
                    }
                }
            }
            .frame(height: 200)
        }
    }
}

/// An older server's chart: rides only.
private struct WeeklyChart: View {
    var weeks: [Overview.WeekBar]
    var units: Units

    private var labelled: Set<String> {
        Set(weeks.reversed().enumerated().filter { $0.offset % 3 == 0 }.map(\.element.label))
    }

    private func value(_ w: Overview.WeekBar) -> Double {
        units.metric ? w.distanceM / 1000 : w.distanceM / 1609.344
    }

    var body: some View {
        Card(title: "Last 12 weeks · \(units.metric ? "km" : "mi")") {
            Chart(weeks) { week in
                BarMark(x: .value("Week", week.label), y: .value("Distance", value(week)))
                    .foregroundStyle(week.current ? Color.accentColor : Color.accentColor.opacity(0.45))
                    .cornerRadius(3)
            }
            .chartXAxis {
                AxisMarks { value in
                    if let label = value.as(String.self), labelled.contains(label) {
                        AxisValueLabel(collisionResolution: .disabled)
                    }
                }
            }
            .frame(height: 180)
        }
    }
}

private struct RecoveryCard: View {
    var recovery: Overview.Recovery

    var body: some View {
        Card(title: recoveryTitle) {
            Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 14) {
                GridRow {
                    Stat(value: recovery.restingHR.map { "\(Units.whole($0)) bpm" } ?? "–", caption: "Resting HR")
                    // Apple's HRV is SDNN through the day, Garmin's RMSSD overnight: the numbers aren't comparable, so say whose it is.
                    Stat(value: recovery.hrv.map { "\(Units.whole($0)) ms" } ?? "–", caption: recovery.hrvKind == "sdnn" ? "HRV (SDNN)" : "HRV")
                    Stat(value: recovery.sleepHours.map { Units.duration(seconds: $0 * 3600) } ?? "–", caption: "Sleep")
                }
                // Apple Health has no sleep score or body battery: leave the row out rather than show dashes.
                if recovery.sleepScore != nil || recovery.bodyBattery != nil || recovery.steps != nil {
                    GridRow {
                        Stat(value: Units.whole(recovery.sleepScore), caption: "Sleep score")
                        Stat(value: Units.whole(recovery.bodyBattery), caption: "Body battery")
                        Stat(value: Units.whole(recovery.steps), caption: "Steps")
                    }
                }
            }
            if let source = sourceLine {
                Text(source).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var sourceLine: String? {
        switch recovery.source {
        case "apple_health": "From Apple Health"
        case "apple_health+garmin": "From Garmin and Apple Health"
        default: nil
        }
    }

    /// The server's date is a local calendar day, so it's read as midnight here (as TodayView.title does), not in UTC.
    private var recoveryTitle: String {
        guard let s = recovery.date else { return "Recovery" }
        let title = TodayView.title(for: s)
        return title == "Today" ? "Recovery · today" : "Recovery · \(title)"
    }
}
