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

                        TotalsCard(totals: overview.totals(for: period),
                                   workouts: overview.workouts?[period.rawValue],
                                   units: session.units)
                        WeeklyChart(weeks: overview.weekly, units: session.units)
                        if let recovery = overview.recovery {
                            RecoveryCard(recovery: recovery)
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
                        Stat(value: "\(workouts.count) · \(units.distance(metres: workouts.distanceM))", caption: "Walks & runs")
                    } else {
                        Color.clear.frame(height: 1)
                    }
                }
            }
        }
    }
}

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
                // Every third week, counted back from this one: twelve "27 Jul"s don't fit across a phone.
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
                    Stat(value: recovery.hrv.map { "\(Units.whole($0)) ms" } ?? "–", caption: "HRV")
                    Stat(value: Units.whole(recovery.bodyBattery), caption: "Body battery")
                }
                GridRow {
                    Stat(value: recovery.sleepHours.map { Units.duration(seconds: $0 * 3600) } ?? "–", caption: "Sleep")
                    Stat(value: Units.whole(recovery.sleepScore), caption: "Sleep score")
                    Stat(value: Units.whole(recovery.steps), caption: "Steps")
                }
            }
        }
    }

    private var recoveryTitle: String {
        guard let s = recovery.date, let date = try? Date(s, strategy: .iso8601.year().month().day()) else { return "Recovery" }
        return Calendar.current.isDateInToday(date) ? "Recovery · today" : "Recovery · \(date.formatted(.dateTime.day().month()))"
    }
}
