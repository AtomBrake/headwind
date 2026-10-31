import SwiftUI

struct SettingsView: View {
    @Environment(Session.self) private var session
    @State private var confirmUnpair = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    LabeledContent("Address", value: session.pairing?.server.absoluteString ?? "–")
                    LabeledContent("Rider", value: session.info?.rider ?? "–")
                    LabeledContent("Units", value: session.units.metric ? "Metric" : "Imperial")
                    if let server = session.pairing?.server {
                        Link("Open Headwind in Safari", destination: server)
                    }
                }

                Section {
                    Button("Unpair this phone", role: .destructive) { confirmUnpair = true }
                } footer: {
                    Text("Unpairing forgets the token on this phone. To stop the token working entirely, revoke it on your server's Phones page too.")
                }

                Section {
                    LabeledContent("App version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "–")
                    LabeledContent("Server API", value: session.info?.api.map(String.init) ?? "–")
                }
            }
            .navigationTitle("Settings")
            .confirmationDialog("Unpair this phone?", isPresented: $confirmUnpair, titleVisibility: .visible) {
                Button("Unpair", role: .destructive) { session.unpair() }
            }
        }
    }
}
