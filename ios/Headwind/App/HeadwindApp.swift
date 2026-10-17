import SwiftUI

@main
struct HeadwindApp: App {
    @State private var session: Session
    @State private var store: RideStore
    @State private var recorder: PhoneRideRecorder
    /// Made at launch, not lazily: iOS may start the app in the background just to deliver a Watch ride.
    @State private var watch: WatchBridge
    @State private var recordRouter = Router()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        let session = Session()
        let store = RideStore()
        let recorder = PhoneRideRecorder()
        let watch = WatchBridge(store: store)
        watch.onRideReceived = { Task { await store.uploadPending(using: session) } }
        recorder.postLive = { update in
            // Best effort: Home Assistant missing one position doesn't matter; the ride itself is journalled.
            // Not through session.call, so a 401 here doesn't unpair the phone mid-ride.
            guard let pairing = session.pairing else { return }
            _ = try? await APIClient(pairing: pairing).post("live", json: update, as: Ignored.self)
        }
        _session = State(initialValue: session)
        _store = State(initialValue: store)
        _recorder = State(initialValue: recorder)
        _watch = State(initialValue: watch)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .environment(store)
                .environment(recorder)
                .environment(watch)
                .environment(recordRouter)
                .onOpenURL { session.handle(url: $0) }
                .onChange(of: session.info, initial: true) { syncWatch() }
                .onChange(of: session.pairing) { syncWatch() }
        }
        .onChange(of: scenePhase) { _, phase in
            // Retry anything that failed to upload while offline.
            if phase == .active { Task { await store.uploadPending(using: session) } }
        }
    }

    private func syncWatch() {
        watch.updateWatch(units: session.info?.units, paired: session.pairing != nil)
    }
}

/// For replies whose content the app doesn't need.
struct Ignored: Decodable, Sendable {}

struct RootView: View {
    @Environment(Session.self) private var session
    @Environment(PhoneRideRecorder.self) private var recorder

    var body: some View {
        Group {
            if session.pairing != nil {
                MainTabs()
            } else if recorder.isRecording {
                // Unpaired mid-ride (token revoked, or a new pairing link accepted): keep Pause and Finish
                // reachable. The ride is stored on the phone and uploads once paired again.
                RecordView()
            } else {
                PairingView()
            }
        }
        .alert("Pair with a different server?", isPresented: switchPrompt) {
            Button("Pair", role: .destructive) {
                guard let link = session.pendingLink else { return }
                session.unpair()
                session.pendingLink = link   // PairingView takes it from here
            }
            Button("Cancel", role: .cancel) { session.pendingLink = nil }
        } message: {
            Text("This phone is paired with \(session.pairing?.server.host() ?? "a server"). Opening this code replaces that pairing.")
        }
    }

    /// Only prompt when already paired; unpaired, PairingView consumes the link itself. Both buttons settle
    /// pendingLink themselves, so the setter does nothing (SwiftUI may call it before a button's action runs).
    private var switchPrompt: Binding<Bool> {
        Binding(get: { session.pairing != nil && session.pendingLink != nil }, set: { _ in })
    }
}

struct MainTabs: View {
    @Environment(Session.self) private var session

    var body: some View {
        TabView {
            TodayView()
                .tabItem { Label("Today", systemImage: "fork.knife") }
            RecordView()
                .tabItem { Label("Record", systemImage: "record.circle") }
            OverviewView()
                .tabItem { Label("Overview", systemImage: "chart.bar") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape") }
        }
        .task { await session.refreshInfo() }
    }
}
