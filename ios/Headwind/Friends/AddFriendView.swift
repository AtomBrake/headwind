import SwiftUI

/// Add a friend from the code they made for you: scanned, pasted, or opened as a headwind://friend link. The server checks the
/// code against the friend's Headwind, then this picks which of their riders to follow and what to call them, as on the web.
struct AddFriendView: View {
    @Environment(Session.self) private var session
    @Environment(\.dismiss) private var dismiss

    /// A code that came with the view (a headwind://friend link opened from the Camera app).
    var initialCode: String?

    @State private var text = ""
    @State private var scanning = false
    @State private var code: String?
    @State private var probe: FriendProbe?
    @State private var rider = ""
    @State private var name = ""
    @State private var busy = false
    @State private var error: AppError?
    @State private var added: String?

    var body: some View {
        NavigationStack {
            Form {
                if let added {
                    Section {
                        Label("\(added) added. Their activities appear once the first sync finishes.", systemImage: "checkmark.circle")
                    }
                } else if let probe {
                    connected(probe)
                } else {
                    enterCode
                }
                if busy {
                    Section { HStack { ProgressView(); Text(probe == nil ? "Checking their Headwind…" : "Adding…") } }
                }
                if let error {
                    Section { Text(error.localizedDescription).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Add a friend")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: added == nil ? .cancellationAction : .confirmationAction) {
                    Button(added == nil ? "Cancel" : "Done") { dismiss() }
                }
            }
            .sheet(isPresented: $scanning) {
                QRScannerSheet(title: "Scan friend's code") { scanned in
                    scanning = false
                    text = scanned
                    Task { await check(scanned) }
                }
            }
            .task {
                if let initialCode, code == nil { await check(initialCode) }
            }
        }
    }

    @ViewBuilder private var enterCode: some View {
        Section {
            Button {
                scanning = true
            } label: {
                Label("Scan QR code", systemImage: "qrcode.viewfinder")
            }
        } footer: {
            Text("Your friend makes a code for you on their Headwind: Friends → Who Can Read Your Feed, or Settings → Share with a friend in their app.")
        }
        Section("Or paste their code") {
            TextField("hwfc_…", text: $text, axis: .vertical)
                .font(.callout.monospaced())
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Connect") { Task { await check(text) } }
                .disabled(busy || text.isEmpty)
        }
    }

    @ViewBuilder private func connected(_ probe: FriendProbe) -> some View {
        Section {
            LabeledContent("Their Headwind", value: URL(string: probe.url)?.host() ?? probe.url)
            if probe.riders.count > 1 {
                Picker("Rider", selection: $rider) {
                    ForEach(probe.riders, id: \.self) { r in
                        Text(r.name + (r.isDefault ? " (default)" : "")).tag(r.name)
                    }
                }
            }
            TextField("Show them here as", text: $name)
        } footer: {
            Text("Their activities, segments and foods arrive with the first sync, and keep coming on your Headwind's sync schedule.")
        }
        Section {
            Button("Add & Sync") { Task { await add() } }
                .disabled(busy || name.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private func check(_ input: String) async {
        guard let found = FriendLink.code(in: input) else {
            error = .validationError(message: "That isn't a friend code from Headwind. It starts hwfc_.")
            return
        }
        await run { () async throws(AppError) in
            let p = try await session.call { client async throws(AppError) in
                try await client.post("friends/probe", json: ["code": found], as: FriendProbe.self)
            }
            let first = p.riders.first { $0.isDefault } ?? p.riders.first
            code = found
            rider = first?.name ?? ""
            name = first.map { $0.name == "Default rider" ? "" : $0.name } ?? ""
            probe = p
        }
    }

    private func add() async {
        guard let code else { return }
        let body = FriendAddRequest(code: code, rider: rider, name: name.trimmingCharacters(in: .whitespaces))
        await run { () async throws(AppError) in
            _ = try await session.call { client async throws(AppError) in
                try await client.post("friends", json: body, as: Ignored.self)
            }
            added = body.name
        }
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
