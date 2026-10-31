import SwiftUI

struct PairingView: View {
    @Environment(Session.self) private var session

    @State private var scanning = false
    @State private var server = ""
    @State private var token = ""
    @State private var busy = false
    @State private var error: AppError?

    var body: some View {
        NavigationStack {
            Form {
                Section { PairingHeader() }
                    .listRowBackground(Color.clear)

                if session.wasRevoked {
                    Section {
                        Label("The server stopped accepting this phone's token, so it was unpaired. Create a new pairing to continue.",
                              systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                    }
                }

                Section {
                    Button {
                        scanning = true
                    } label: {
                        Label("Scan QR code", systemImage: "qrcode.viewfinder")
                    }
                    .disabled(busy)
                } footer: {
                    Text("You can also point the iPhone's Camera app at the code; it will offer to open Headwind.")
                }

                Section {
                    ManualPairingFields(server: $server, token: $token, busy: busy) {
                        Task { await pairManually() }
                    }
                }

                if busy {
                    Section { HStack { ProgressView(); Text("Checking the server…") } }
                }
                if let error {
                    Section { Text(error.localizedDescription).foregroundStyle(.red) }
                }
            }
            .sheet(isPresented: $scanning) {
                QRScannerSheet { code in
                    scanning = false
                    Task { await pair(link: code) }
                }
            }
            .task(id: session.pendingLink) {
                // A headwind://pair link opened from outside the app while unpaired.
                guard let link = session.pendingLink else { return }
                session.pendingLink = nil
                await pair(link: link)
            }
        }
    }

    private func pairManually() async {
        // The token field also accepts the whole headwind://pair link, as shown in text under the QR on the Phones page.
        guard !token.lowercased().hasPrefix("headwind://") else {
            await pair(link: token)
            return
        }
        await run { () async throws(AppError) in
            try await session.pair(with: PairLink.make(server: server, token: token))
        }
    }

    private func pair(link: String) async {
        await run { () async throws(AppError) in try await session.pair(link: link) }
    }

    private func run(_ action: () async throws(AppError) -> Void) async {
        busy = true
        error = nil
        defer { busy = false }
        do throws(AppError) {
            try await action()
        } catch {
            self.error = error
        }
    }
}

private struct PairingHeader: View {
    var body: some View {
        VStack(spacing: 12) {
            Image("Logo")
                .resizable()
                .frame(width: 96, height: 96)
                .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
            Text("Pair with your Headwind")
                .font(.title2.bold())
            Text("On your Headwind server, open **Phones**, give this phone a name and create a pairing. Then scan the QR code it shows.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
    }
}

/// Server address and token typed or pasted in, for when scanning isn't possible.
private struct ManualPairingFields: View {
    @Binding var server: String
    @Binding var token: String
    var busy: Bool
    var onPair: () -> Void
    @State private var expanded = false

    var body: some View {
        DisclosureGroup("Enter details manually", isExpanded: $expanded) {
            TextField("https://bike.example.com", text: $server)
                .keyboardType(.URL)
                .textContentType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("Token (hw_…) or pairing link", text: $token)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Pair", action: onPair)
                .disabled(busy || token.isEmpty)
        }
    }
}

#Preview {
    PairingView().environment(Session(store: MemoryPairingStore()))
}
