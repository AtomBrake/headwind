import SwiftUI
import UIKit

/// The Record screen's "Share live location" switch: before Start, whether the recording starts with a link; mid-recording, starting one
/// (with the track so far) or stopping it. Only for sports with GPS: a timer has no position to share.
struct LiveShareSwitch: View {
    var recorder: PhoneRideRecorder
    @Environment(LiveShareController.self) private var live
    @Environment(Session.self) private var session

    var body: some View {
        if recorder.sport.usesGPS {
            VStack(alignment: .leading, spacing: 4) {
                Toggle(isOn: isOn) {
                    Label("Share live location", systemImage: "dot.radiowaves.left.and.right")
                        .font(.callout)
                }
                .disabled(session.pairing == nil || live.busy)
                .accessibilityIdentifier("share-live")
                if session.pairing == nil {
                    Text("Needs a paired server.").font(.caption).foregroundStyle(.secondary)
                } else if live.busy {
                    HStack(spacing: 6) { ProgressView().controlSize(.small); Text("Making the link…") }
                        .font(.caption).foregroundStyle(.secondary)
                } else if isOn.wrappedValue {
                    Text("You'll get a link to send. Anyone with the link can see where you are.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }

    private var isOn: Binding<Bool> {
        Binding(get: {
            recorder.isRecording ? live.isSharing(recorder.recordingID) || live.busy : live.wanted
        }, set: { on in
            guard recorder.isRecording else {
                live.wanted = on
                return
            }
            Task {
                if on {
                    await live.start(recorder: recorder, pairing: session.pairing)
                } else {
                    await live.stop(recorder: recorder, pairing: session.pairing)
                }
            }
        })
    }
}

/// The link while it works: during the recording, and for the hour after it ends. Send it again, copy it, or stop it.
struct LiveLinkCard: View {
    var link: LiveShareController.Link
    var recorder: PhoneRideRecorder
    @Environment(LiveShareController.self) private var live
    @Environment(Session.self) private var session
    @State private var copied = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(link.ended ? "Live link" : link.fromWatch == true ? "Sharing live location from your Watch" : "Sharing live location",
                  systemImage: link.ended ? "flag.checkered" : "dot.radiowaves.left.and.right")
                .font(.callout.weight(.semibold))
                .foregroundStyle(link.ended ? Color.primary : Color.green)
            Text(link.ended
                 ? "Your recording has finished. Anyone with the link can see it until \(link.expiresAt.formatted(date: .omitted, time: .shortened))."
                 : "Anyone with the link can see where you are, until an hour after you finish.")
                .font(.caption)
                .foregroundStyle(.secondary)
            HStack(spacing: 8) {
                Button {
                    live.outgoing = .init(url: link.url, sport: link.sport.map { Sport(stored: $0) } ?? recorder.sport)
                } label: {
                    Label("Send", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(.borderedProminent)
                Button {
                    UIPasteboard.general.url = link.url
                    copied = true
                } label: {
                    Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(.bordered)
                Spacer(minLength: 0)
                Button("Stop sharing", role: .destructive) {
                    Task { await live.stop(recorder: recorder, pairing: session.pairing) }
                }
                .buttonStyle(.bordered)
                .disabled(live.busy)
                .accessibilityIdentifier("stop-sharing")
            }
            .controlSize(.small)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

/// The share sheet (Messages, WhatsApp, Mail ...) for a live link.
struct LiveLinkShareSheet: UIViewControllerRepresentable {
    var outgoing: LiveShareController.Outgoing

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let what = outgoing.sport.title.lowercased()        // "ride", "e-bike ride", "run", "open water swim"
        let controller = UIActivityViewController(activityItems: ["Follow my \(what) live:", outgoing.url], applicationActivities: nil)
        controller.setValue("Follow my \(what) live", forKey: "subject")      // Mail's subject line
        return controller
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
