import SwiftUI

/// One of the rider's contacts (GET /api/v1/contacts, services/contacts.py on the server): emailed each live tracking link as it starts,
/// when `liveLinks` is on.
struct Contact: Decodable, Identifiable, Sendable, Equatable {
    var id: Int
    var name: String
    var email: String
    var liveLinks: Bool
}

/// GET /api/v1/contacts reply: the contacts, and whether the server can send email at all.
struct ContactList: Decodable, Sendable {
    struct Email: Decodable, Sendable {
        var ready: Bool
        /// Why not, fit to show.
        var error: String?
        var settingsUrl: String?
    }

    var contacts: [Contact]
    var email: Email
}

/// Body of POST /api/v1/contacts and PATCH /api/v1/contacts/<id> (any of its fields).
struct ContactChange: Encodable, Sendable {
    var name: String?
    var email: String?
    var live_links: Bool?
}

struct ContactRemoved: Decodable, Sendable {
    var deleted: Bool
}

/// Settings → Contacts: the people the server emails each live tracking link to as it starts, so it gets out with nobody tapping anything,
/// from the Watch on its own too. The same list as Settings on the web; it's kept on the server.
struct ContactsView: View {
    @Environment(Session.self) private var session
    @State private var list: ContactList?
    @State private var error: String?
    @State private var adding = false
    @State private var loading = false

    var body: some View {
        Form {
            if let email = list?.email, !email.ready {
                Section {
                    Label(email.error ?? "Your server can't send email yet.", systemImage: "exclamationmark.triangle")
                        .font(.callout)
                        .foregroundStyle(.orange)
                    if let server = session.pairing?.server, let path = email.settingsUrl,
                       let url = URL(string: path, relativeTo: server)?.absoluteURL {
                        Link("Set up email on the web", destination: url)
                    }
                }
            }
            Section {
                if let contacts = list?.contacts {
                    if contacts.isEmpty {
                        Text("No contacts yet.").foregroundStyle(.secondary)
                    }
                    ForEach(contacts) { contact in
                        Toggle(isOn: Binding(get: { contact.liveLinks }, set: { on in Task { await set(contact, liveLinks: on) } })) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(contact.name)
                                Text(contact.email).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .accessibilityIdentifier("contact-\(contact.id)")
                    }
                    .onDelete { offsets in
                        let gone = offsets.map { contacts[$0] }
                        Task { for c in gone { await remove(c) } }
                    }
                } else if loading {
                    ProgressView()
                }
                Button {
                    adding = true
                } label: {
                    Label("Add a contact", systemImage: "person.badge.plus")
                }
                .disabled(session.pairing == nil || list == nil)
            } footer: {
                Text("Switched on, a contact is emailed each live tracking link as it starts, by your server: from the Watch on its own too, with nobody tapping anything. The email says it's from you, and that the link stops working an hour after you finish.")
            }
            if let error {
                Section {
                    Label(error, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
                }
            }
        }
        .navigationTitle("Contacts")
        .task { await load() }
        .refreshable { await load() }
        .sheet(isPresented: $adding) {
            AddContactView { name, email in await add(name: name, email: email) }
        }
    }

    private var client: APIClient? { session.pairing.map { APIClient(pairing: $0) } }

    private func load() async {
        guard let client else {
            error = AppError.notPaired.localizedDescription
            return
        }
        loading = true
        defer { loading = false }
        do throws(AppError) {
            list = try await client.get("contacts", as: ContactList.self)
            error = nil
        } catch {
            self.error = "Couldn't load your contacts: \(error.localizedDescription)"
        }
    }

    private func set(_ contact: Contact, liveLinks: Bool) async {
        guard let client else { return }
        do throws(AppError) {
            let saved = try await client.patch("contacts/\(contact.id)", json: ContactChange(live_links: liveLinks), as: Contact.self)
            replace(saved)
        } catch {
            self.error = "Couldn't change \(contact.name): \(error.localizedDescription)"
        }
    }

    private func remove(_ contact: Contact) async {
        guard let client else { return }
        do throws(AppError) {
            _ = try await client.delete("contacts/\(contact.id)", as: ContactRemoved.self)
            list?.contacts.removeAll { $0.id == contact.id }
        } catch {
            self.error = "Couldn't remove \(contact.name): \(error.localizedDescription)"
        }
    }

    /// Nil when added; else why not, to show in the sheet.
    private func add(name: String, email: String) async -> String? {
        guard let client else { return AppError.notPaired.localizedDescription }
        do throws(AppError) {
            let made = try await client.post("contacts", json: ContactChange(name: name, email: email, live_links: true), as: Contact.self)
            list?.contacts.append(made)
            list?.contacts.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            return nil
        } catch {
            if case .serverError(_, let message?) = error { return message }       // the server's words: "x is not an email address"
            return error.localizedDescription
        }
    }

    private func replace(_ contact: Contact) {
        guard let i = list?.contacts.firstIndex(where: { $0.id == contact.id }) else { return }
        list?.contacts[i] = contact
    }
}

/// A name and an email address for a new contact.
private struct AddContactView: View {
    var add: (String, String) async -> String?
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var email = ""
    @State private var problem: String?
    @State private var saving = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $name)
                        .textContentType(.name)
                    TextField("Email address", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } footer: {
                    Text("They're emailed each live tracking link as it starts. Switch that off for a while in the list.")
                }
                if let problem {
                    Text(problem).font(.caption).foregroundStyle(.orange)
                }
            }
            .navigationTitle("Add a contact")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        saving = true
                        Task {
                            problem = await add(name, email)
                            saving = false
                            if problem == nil { dismiss() }
                        }
                    }
                    .disabled(saving || name.trimmingCharacters(in: .whitespaces).isEmpty || !email.contains("@"))
                }
            }
        }
    }
}
