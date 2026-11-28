import ActivityKit
import SwiftUI
import WidgetKit

/// The HeadwindWidgets extension: the recording's Live Activity (RecordingActivityAttributes), started by the app at Start and ended at
/// Finish or Discard. The Lock Screen shows the sport, the time, distance, speed or pace and heart rate, and whether the live link is
/// being shared; the Dynamic Island the same, smaller.
@main
struct HeadwindWidgets: WidgetBundle {
    var body: some Widget {
        RecordingLiveActivity()
    }
}

struct RecordingLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: RecordingActivityAttributes.self) { context in
            LockScreenView(attributes: context.attributes, state: context.state)
                .padding()
                .activityBackgroundTint(Color.black.opacity(0.6))
                .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            let state = context.state
            return DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    Label(context.attributes.sport, systemImage: context.attributes.symbol)
                        .font(.headline)
                        .lineLimit(1)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    ElapsedText(state: state)
                        .font(.title3.monospacedDigit())
                        .multilineTextAlignment(.trailing)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack {
                        Figures(state: state)
                        Spacer()
                        SharingBadge(sharing: state.sharing)
                    }
                }
            } compactLeading: {
                Image(systemName: context.attributes.symbol)
                    .foregroundStyle(state.sharing ? .green : .primary)
            } compactTrailing: {
                ElapsedText(state: state)
                    .monospacedDigit()
                    .frame(maxWidth: 64)
            } minimal: {
                Image(systemName: context.attributes.symbol)
                    .foregroundStyle(state.sharing ? .green : .primary)
            }
        }
    }
}

/// The time so far: counting up by itself while recording, still while paused.
private struct ElapsedText: View {
    var state: RecordingActivityAttributes.ContentState

    var body: some View {
        if let paused = state.pausedElapsed {
            Text(RecordingActivityAttributes.ContentState.clock(paused)) + Text(" ⏸")
        } else {
            Text(timerInterval: state.timerStart...Date.distantFuture, countsDown: false)
        }
    }
}

private struct Figures: View {
    var state: RecordingActivityAttributes.ContentState

    var body: some View {
        HStack(spacing: 14) {
            if let distance = state.distance { figure(distance, "Distance") }
            if let rate = state.rate { figure(rate, state.rateCaption) }
            if let hr = state.heartRate { figure("\(hr)", "bpm") }
        }
    }

    private func figure(_ value: String, _ caption: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(value).font(.headline.monospacedDigit()).lineLimit(1).minimumScaleFactor(0.7)
            Text(caption).font(.caption2).foregroundStyle(.secondary)
        }
    }
}

private struct SharingBadge: View {
    var sharing: Bool

    var body: some View {
        if sharing {
            Label("Sharing", systemImage: "location.fill.viewfinder")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.green)
        }
    }
}

private struct LockScreenView: View {
    var attributes: RecordingActivityAttributes
    var state: RecordingActivityAttributes.ContentState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(attributes.sport, systemImage: attributes.symbol).font(.headline)
                Spacer()
                ElapsedText(state: state).font(.title2.monospacedDigit().weight(.semibold))
            }
            HStack {
                Figures(state: state)
                Spacer()
                SharingBadge(sharing: state.sharing)
            }
            if state.sharing {
                Text("Your live link is on: whoever has it sees where you are.")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .foregroundStyle(.white)
    }
}
