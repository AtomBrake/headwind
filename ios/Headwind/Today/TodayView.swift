import SwiftUI

struct TodayView: View {
    @Environment(Session.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    @State private var today: Today?
    @State private var error: AppError?

    var body: some View {
        NavigationStack {
            Loaded(value: today, error: error, retry: load) { today in
                ScrollView {
                    CardColumns {
                        CaloriesCard(today: today)
                        MacrosCard(today: today)
                        HStack(alignment: .top, spacing: 16) {
                            Card(title: "Water") {
                                GoalBar(label: "", value: today.waterMl, goal: today.waterGoalMl ?? today.goals?.water,
                                        unit: " ml", tint: .cyan)
                            }
                            Card(title: "Steps") {
                                GoalBar(label: "", value: today.steps?.today, goal: today.steps?.goal, tint: .green)
                            }
                        }
                        if let weight = today.weight, weight.raw != nil || weight.trend != nil {
                            WeightCard(weight: weight)
                        }
                        if let workouts = today.workouts, !workouts.isEmpty {
                            ActivitiesCard(workouts: workouts, units: session.units)
                        }
                        DiaryCard(entries: today.entries ?? [])
                    }
                    .padding(16)
                }
                .background(Color(.systemGroupedBackground))
                .refreshable { await load() }
            }
            .navigationTitle(title)
        }
        .task { await load() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await load() } }
        }
    }

    private var title: String { today.map { Self.title(for: $0.date) } ?? "Today" }

    /// "Today", or the day the server's date is ("Friday 16 October"). The server sends a local calendar date, so it's read as
    /// midnight here, not in UTC: read as UTC, west of Greenwich it fell on the evening before.
    nonisolated static func title(for day: String, now: Date = .now, calendar: Calendar = .current) -> String {
        let parts = day.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, let date = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])) else {
            return "Today"
        }
        if calendar.isDate(date, inSameDayAs: now) { return "Today" }
        var style = Date.FormatStyle.dateTime.weekday(.wide).day().month()
        style.timeZone = calendar.timeZone
        return date.formatted(style)
    }

    private func load() async {
        do throws(AppError) {
            today = try await session.load("today")
            error = nil
        } catch {
            self.error = error
        }
    }
}

private struct CaloriesCard: View {
    var today: Today

    private var eaten: Double { today.eaten?.calories ?? 0 }
    private var goal: Double? { today.goals?.cal }

    var body: some View {
        Card(title: "Calories") {
            HStack(spacing: 20) {
                ZStack {
                    Circle().stroke(Color.accentColor.opacity(0.15), lineWidth: 12)
                    Circle()
                        .trim(from: 0, to: min(eaten / max(goal ?? eaten, 1), 1))
                        .stroke(eaten > (goal ?? .infinity) ? Color.orange : Color.accentColor,
                                style: StrokeStyle(lineWidth: 12, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                    VStack(spacing: 0) {
                        Text(Units.whole(today.remaining?.calories ?? goal.map { $0 - eaten }))
                            .font(.title2.bold())
                            .monospacedDigit()
                        Text((today.remaining?.calories ?? 0) < 0 ? "over" : "left")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(width: 110, height: 110)

                VStack(alignment: .leading, spacing: 10) {
                    Stat(value: Units.whole(eaten), caption: "Eaten")
                    Stat(value: Units.whole(goal), caption: "Goal")
                    Stat(value: Units.whole(today.burned), caption: today.burnSource.map { "Burned · \($0)" } ?? "Burned")
                }
            }
        }
    }
}

private struct MacrosCard: View {
    var today: Today

    var body: some View {
        Card(title: "Macros") {
            GoalBar(label: "Protein", value: today.eaten?.protein, goal: today.goals?.protein, unit: " g", tint: .pink)
            GoalBar(label: "Carbs", value: today.eaten?.carbs, goal: today.goals?.carbs, unit: " g", tint: .yellow)
            GoalBar(label: "Fat", value: today.eaten?.fat, goal: today.goals?.fat, unit: " g", tint: .purple)
            GoalBar(label: "Fibre", value: today.eaten?.fibre, goal: today.goals?.fibre, unit: " g", tint: .green)
        }
    }
}

private struct WeightCard: View {
    var weight: Today.WeightSnapshot

    var body: some View {
        Card(title: "Weight") {
            HStack {
                Stat(value: weight.trend.map { Units.weight(kg: $0, unit: weight.unit) } ?? "–", caption: "Trend")
                Stat(value: weight.raw.map { Units.weight(kg: $0, unit: weight.unit) } ?? "Not logged", caption: "Today")
                if let fat = weight.bodyFat {
                    Stat(value: fat.formatted(.number.precision(.fractionLength(1))) + "%", caption: "Body fat")
                }
            }
        }
    }
}

private struct DiaryCard: View {
    var entries: [FoodEntry]

    /// The server's meal names, in the order the web diary shows them; anything else goes last.
    private static let order = ["breakfast", "lunch", "dinner", "snacks", "uncategorised"]

    private var meals: [(name: String, items: [FoodEntry])] {
        let grouped = Dictionary(grouping: entries) { $0.mealType ?? "uncategorised" }
        return grouped.keys
            .sorted { (Self.order.firstIndex(of: $0) ?? 99, $0) < (Self.order.firstIndex(of: $1) ?? 99, $1) }
            .map { ($0, grouped[$0]!) }
    }

    var body: some View {
        Card(title: "Food diary") {
            if entries.isEmpty {
                Text("Nothing logged yet today.")
                    .foregroundStyle(.secondary)
            }
            ForEach(meals, id: \.name) { meal in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(meal.name == "uncategorised" ? "Other" : meal.name.capitalized)
                            .font(.subheadline.weight(.semibold))
                        Spacer()
                        Text("\(Units.whole(meal.items.reduce(0) { $0 + ($1.calories ?? 0) })) kcal")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .monospacedDigit()
                    }
                    ForEach(meal.items) { item in
                        HStack(alignment: .firstTextBaseline) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(item.foodName)
                                if let brand = item.brand, !brand.isEmpty {
                                    Text(brand).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            Text(Units.whole(item.calories))
                                .monospacedDigit()
                                .foregroundStyle(.secondary)
                        }
                        .font(.callout)
                    }
                }
                if meal.name != meals.last?.name { Divider() }
            }
        }
    }
}

/// Today's activities that aren't rides (the server's /today `workouts`): a walk, a swim, a strength session, each with its own icon and label.
private struct ActivitiesCard: View {
    var workouts: [Workout]
    var units: Units

    var body: some View {
        Card(title: "Activities") {
            ForEach(workouts) { w in
                HStack {
                    Image(systemName: ActivitySport.systemImage(w.sport))
                        .foregroundStyle(Color.accentColor)
                        .frame(width: 24)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(w.name ?? w.label ?? w.sport ?? "Activity")
                        if w.name != nil, let label = w.label ?? w.sport {
                            Text(label).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Text(details(w).joined(separator: " · "))
                        .foregroundStyle(.secondary)
                        .monospacedDigit()
                }
                .font(.callout)
            }
        }
    }

    /// Distance where the sport has one (a swim's in metres), then time.
    private func details(_ w: Workout) -> [String] {
        let sport = Sport(rawValue: w.sport ?? "")
        let distance = w.distance.flatMap { $0 > 0 ? $0 : nil }.map { d in sport.map { units.distance(metres: d, sport: $0) } ?? units.distance(metres: d) }
        return [distance, w.movingTime.map { Units.duration(seconds: $0) }].compactMap { $0 }
    }
}
