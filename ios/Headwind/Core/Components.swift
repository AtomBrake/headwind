import SwiftUI

/// The rounded panel every dashboard section sits in.
struct Card<Content: View>: View {
    var title: String?
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

/// A labelled bar with "value / goal" — used for macros, water and steps.
struct GoalBar: View {
    var label: String
    var value: Double?
    var goal: Double?
    var unit: String = ""
    var tint: Color = .accentColor

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label)
                Spacer()
                Text(goal.map { "\(Units.whole(value)) / \(Units.whole($0))\(unit)" } ?? "\(Units.whole(value))\(unit)")
                    .monospacedDigit()
                    .foregroundStyle(.secondary)
            }
            .font(.subheadline)
            ProgressView(value: min(value ?? 0, goal ?? 1), total: max(goal ?? 1, 1))
                .tint((value ?? 0) > (goal ?? .infinity) ? .orange : tint)
        }
    }
}

/// A big number with a caption underneath, for stat grids.
struct Stat: View {
    var value: String
    var caption: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.title3.weight(.semibold))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(caption)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Loading / error / content switch shared by the tabs. Keeps showing the last good data while refreshing.
struct Loaded<Value, Content: View>: View {
    var value: Value?
    var error: AppError?
    var retry: () async -> Void
    @ViewBuilder var content: (Value) -> Content

    var body: some View {
        if let value {
            content(value)
        } else if let error {
            ContentUnavailableView {
                Label("Couldn't reach Headwind", systemImage: "wifi.exclamationmark")
            } description: {
                Text(error.localizedDescription)
            } actions: {
                Button("Try again") { Task { await retry() } }
                    .buttonStyle(.borderedProminent)
            }
        } else {
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

/// The cards of a dashboard tab: one column on a phone held upright (or the iPhone Duo's outer screen), side by side when there's room (a
/// phone on its side, the Duo's inner screen). Follows the size class, never the screen's size, so unfolding mid-scroll just re-flows the
/// cards and keeps every view's state.
struct CardColumns<Content: View>: View {
    @Environment(\.horizontalSizeClass) private var sizeClass
    var spacing: CGFloat = 16
    @ViewBuilder var content: Content

    var body: some View {
        if sizeClass == .regular {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 340), spacing: spacing, alignment: .top)], alignment: .leading, spacing: spacing) {
                content
            }
        } else {
            VStack(spacing: spacing) { content }
        }
    }
}

