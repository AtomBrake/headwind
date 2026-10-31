import CoreImage.CIFilterBuiltins
import SwiftUI

/// Make a code for one friend, as Friends → Who Can Read Your Feed on the web: their name, what they may see, then a QR code
/// for their Headwind app to scan, or the code itself to send them.
struct ShareWithFriendView: View {
    @Environment(Session.self) private var session

    @State private var name = ""
    @State private var rides = true
    @State private var segments = true
    @State private var foods = true
    @State private var range = ShareRange.all
    @State private var since = Calendar.current.date(byAdding: .month, value: -1, to: .now) ?? .now
    @State private var hasUntil = false
    @State private var until = Date.now
    @State private var busy = false
    @State private var error: AppError?
    @State private var made: (name: String, share: FriendShare)?

    var body: some View {
        Form {
            if let made {
                ShareResult(name: made.name, share: made.share) {
                    self.made = nil
                    name = ""
                }
            } else {
                form
            }
        }
        .navigationTitle("Share with a friend")
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder private var form: some View {
        Section {
            TextField("e.g. Sam", text: $name)
                .textContentType(.name)
        } header: {
            Text("Friend's name")
        } footer: {
            Text("Each friend gets a code of their own, so you can change what one sees, or stop sharing with them, on your Headwind's Friends page.")
        }

        Section("Shares") {
            Toggle("Activities", isOn: $rides)
            Toggle("Segments", isOn: $segments)
            Toggle("Foods", isOn: $foods)
        }

        if rides {
            Section {
                Picker("Activities", selection: $range) {
                    ForEach(ShareRange.allCases) { Text($0.title).tag($0) }
                }
                if range == .custom {
                    DatePicker("From", selection: $since, displayedComponents: .date)
                    Toggle("Up to a date", isOn: $hasUntil)
                    if hasUntil {
                        DatePicker("To", selection: $until, in: since..., displayedComponents: .date)
                    }
                }
            } footer: {
                Text("Every sport is shared: rides, runs, walks, swims and the rest. With no end date, new activities keep flowing.")
            }
        }

        Section {
            Button {
                Task { await create() }
            } label: {
                HStack {
                    Label("Create QR code", systemImage: "qrcode")
                    Spacer()
                    if busy { ProgressView() }
                }
            }
            .disabled(busy || name.trimmingCharacters(in: .whitespaces).isEmpty || !(rides || segments || foods))
        }

        if let error {
            Section { Text(error.localizedDescription).foregroundStyle(.red) }
        }
    }

    private func create() async {
        guard let server = session.pairing?.server else { return }
        let window = range.window(since: since, until: hasUntil ? until : nil)
        let body = FriendTokenRequest(name: name.trimmingCharacters(in: .whitespaces), rides: rides, segments: segments, foods: foods,
                                      since: window.since, until: window.until, server_url: server.absoluteString)
        busy = true
        error = nil
        defer { busy = false }
        do throws(AppError) {
            let share = try await session.call { client async throws(AppError) in
                try await client.post("friends/tokens", json: body, as: FriendShare.self)
            }
            made = (body.name, share)
        } catch {
            self.error = error
        }
    }
}

/// The quick ranges on the web's form, plus dates of your own.
enum ShareRange: String, CaseIterable, Identifiable {
    case all, sixMonths, month, today, custom
    var id: Self { self }

    var title: String {
        switch self {
        case .all: "All"
        case .sixMonths: "Past 6 months"
        case .month: "Past month"
        case .today: "From today"
        case .custom: "Between dates"
        }
    }

    /// The "YYYY-MM-DD" window the server stores; nil ends are open.
    func window(since: Date, until: Date?, now: Date = .now, calendar: Calendar = .current) -> (since: String?, until: String?) {
        let style = Date.ISO8601FormatStyle(timeZone: calendar.timeZone).year().month().day()
        let day = { (d: Date) in d.formatted(style) }
        switch self {
        case .all: return (nil, nil)
        case .sixMonths: return (calendar.date(byAdding: .month, value: -6, to: now).map(day), nil)
        case .month: return (calendar.date(byAdding: .month, value: -1, to: now).map(day), nil)
        case .today: return (day(now), nil)
        case .custom: return (day(since), until.map(day))
        }
    }
}

/// The code, once: a QR code for their app to scan, and the text to send.
private struct ShareResult: View {
    var name: String
    var share: FriendShare
    var onDone: () -> Void

    var body: some View {
        Section {
            VStack(spacing: 12) {
                if let qr = QRCode.image(for: share.link) {
                    Image(decorative: qr, scale: 1)
                        .interpolation(.none)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 260)
                        .padding(10)
                        .background(.white, in: RoundedRectangle(cornerRadius: 12))
                        .accessibilityLabel("QR code for \(name)")
                }
                Text("Ask \(name) to scan this with the Headwind app on their iPhone: Settings → Add a friend, or the Camera app.")
                    .font(.callout)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        } footer: {
            Text("It's shown once. Anyone with the code can read what it shares, so send it privately.")
        }

        Section {
            Text(share.code)
                .font(.caption.monospaced())
                .textSelection(.enabled)
            Button("Copy code", systemImage: "doc.on.doc") { UIPasteboard.general.string = share.code }
            ShareLink(item: share.code, subject: Text("Headwind"),
                      message: Text("Add me on Headwind: paste this under Friends → Add a Friend.")) {
                Label("Send code", systemImage: "square.and.arrow.up")
            }
        } header: {
            Text("Or send the code")
        } footer: {
            Text("They paste it into Friends → Add a Friend on their Headwind. It connects to \(share.url).")
        }

        Section {
            Button("Done", action: onDone)
        }
    }
}

enum QRCode {
    /// A crisp QR code of `text`, about 10 pixels a module.
    static func image(for text: String) -> CGImage? {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(text.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 10, y: 10)) else { return nil }
        return CIContext().createCGImage(output, from: output.extent)
    }
}
