import SwiftUI

@main
struct HeadwindApp: App {
    @State private var session: Session
    @State private var store: RideStore
    @State private var recorder: PhoneRideRecorder
    /// Made at launch, not lazily: iOS may start the app in the background just to deliver a Watch ride.
    @State private var watch: WatchBridge
    /// Made at launch too: HealthKit's background delivery only keeps waking the app if its observer queries are set up every launch.
    @State private var health: HealthSync
    @State private var recordRouter = Router()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        let session = Session()
        let store = RideStore()
        let recorder = PhoneRideRecorder()
        let watch = WatchBridge(store: store)
        let health = HealthSync()
        health.observe(using: session)
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
        _health = State(initialValue: health)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .environment(store)
                .environment(recorder)
                .environment(watch)
                .environment(health)
                .environment(recordRouter)
                .onOpenURL { session.handle(url: $0) }
                .onChange(of: session.info, initial: true) { syncWatch() }
                .onChange(of: session.pairing) { syncWatch() }
        }
        .onChange(of: scenePhase) { _, phase in
            // Retry anything that failed to upload while offline, and send what Apple Health has new.
            if phase == .active {
                Task { await store.uploadPending(using: session) }
                Task { await health.sync(using: session) }
            }
        }
    }

    private func syncWatch() {
        watch.updateWatch(units: session.info?.units, paired: session.pairing != nil, bikes: session.bikes)
        Task { await watch.provisionWatch(using: session) }
    }
}

struct RootView: View {
    @Environment(Session.self) private var session
    @Environment(PhoneRideRecorder.self) private var recorder
    /// Set while a new server is being checked before it replaces the current pairing.
    @State private var switching = false
    @State private var switchError: AppError?

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
                session.pendingLink = nil
                Task { await switchServer(to: link) }
            }
            Button("Cancel", role: .cancel) { session.pendingLink = nil }
        } message: {
            Text(switchMessage)
        }
        .alert("Couldn't pair with the new server", isPresented: Binding(get: { switchError != nil }, set: { if !$0 { switchError = nil } }),
               presenting: switchError) { _ in
            Button("OK", role: .cancel) {}
        } message: { error in
            Text("\(error.localizedDescription)\n\nThis phone is still paired with \(session.pairing?.server.host() ?? "its server").")
        }
        .overlay {
            if switching {
                ProgressView("Checking the new server…")
                    .padding(20)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
            }
        }
    }

    private var switchMessage: String {
        let current = session.pairing?.server.host() ?? "a server"
        guard let link = session.pendingLink, let new = (try? PairLink.parse(link))?.server.host() else {
            return "This phone is paired with \(current). Opening this code replaces that pairing."
        }
        return "This phone is paired with \(current). Opening this code pairs it with \(new) instead."
    }

    /// The new server is checked first (Session.pair stores a pairing only once its server accepts the token), so a stale or
    /// mistyped link leaves the working pairing alone.
    private func switchServer(to link: String) async {
        switching = true
        defer { switching = false }
        do throws(AppError) {
            try await session.pair(link: link)
        } catch {
            switchError = error
        }
    }

    /// Only prompt when already paired; unpaired, PairingView consumes the link itself. Both buttons settle
    /// pendingLink themselves, so the setter does nothing (SwiftUI may call it before a button's action runs).
    private var switchPrompt: Binding<Bool> {
        Binding(get: { session.pairing != nil && session.pendingLink != nil }, set: { _ in })
    }
}

/// The tabs. On iOS 18 they're the adaptable kind, which becomes a sidebar where there's room for one; on a phone, the iPhone Duo's inner
/// screen included, it stays a tab bar the system can move to the side. Each tab keeps its own state across a fold or rotation, since the
/// TabView itself never changes.
struct MainTabs: View {
    @Environment(Session.self) private var session

    var body: some View {
        Group {
            if #available(iOS 18.0, *) {
                TabView {
                    Tab("Today", systemImage: "fork.knife") { TodayView() }
                    Tab("Record", systemImage: "record.circle") { RecordView() }
                    Tab("Activities", systemImage: "list.bullet.rectangle") { ActivitiesView() }
                    Tab("Overview", systemImage: "chart.bar") { OverviewView() }
                    Tab("Settings", systemImage: "gearshape") { SettingsView() }
                }
                .tabViewStyle(.sidebarAdaptable)
            } else {
                TabView {
                    TodayView()
                        .tabItem { Label("Today", systemImage: "fork.knife") }
                    RecordView()
                        .tabItem { Label("Record", systemImage: "record.circle") }
                    ActivitiesView()
                        .tabItem { Label("Activities", systemImage: "list.bullet.rectangle") }
                    OverviewView()
                        .tabItem { Label("Overview", systemImage: "chart.bar") }
                    SettingsView()
                        .tabItem { Label("Settings", systemImage: "gearshape") }
                }
            }
        }
        .task { await session.refreshInfo() }
    }
}
