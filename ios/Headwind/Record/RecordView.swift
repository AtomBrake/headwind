import CoreLocation
import MapKit
import SwiftUI

/// The Record tab: its own NavigationStack, routed through the tab's Router.
struct RecordView: View {
    @Environment(Router.self) private var router

    var body: some View {
        @Bindable var router = router
        NavigationStack(path: $router.path) {
            RecordScreen()
                .navigationDestination(for: Route.self) { route in
                    switch route {
                    case .recordings: RecordingsView()
                    case .sensors: SensorsView()
                    }
                }
        }
    }
}

private struct RecordScreen: View {
    @Environment(Session.self) private var session
    @Environment(PhoneRideRecorder.self) private var recorder
    @Environment(RideStore.self) private var store
    @Environment(WatchBridge.self) private var watch
    @Environment(Router.self) private var router
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var confirmFinish = false
    @State private var justSaved: SavedRide.ID?
    @State private var error: AppError?

    var body: some View {
        // Narrow (a phone upright, the iPhone Duo's outer screen): the controls over the map. Wide (on its side, the Duo open): beside it.
        // The recording lives in PhoneRideRecorder, not here, so switching between the two mid-ride loses nothing.
        Group {
            if sizeClass == .regular {
                HStack(spacing: 0) {
                    backdrop
                    ScrollView { panel.padding(16) }
                        .frame(width: 380)
                        .background(Color(.systemGroupedBackground))
                }
            } else {
                ZStack(alignment: .bottom) {
                    backdrop
                    panel.padding(16)
                }
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button { router.show(.sensors) } label: {
                    Label("Sensors", systemImage: "sensor")
                }
                .accessibilityIdentifier("sensors")
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button { router.show(.recordings) } label: {
                    Label("Recordings", systemImage: "list.bullet")
                }
                .badge(store.pendingCount)
                .accessibilityIdentifier("recordings")
            }
        }
        .confirmationDialog("Finish this \(recorder.sport.title.lowercased())?", isPresented: $confirmFinish, titleVisibility: .visible) {
            Button("Save \(recorder.sport.title.lowercased())") { save(recovered: false) }
            Button("Discard \(recorder.sport.title.lowercased())", role: .destructive) { recorder.discard() }
            Button("Keep going", role: .cancel) {}
        }
        .alert("Couldn't save the ride", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
               presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { error in
            Text(error.localizedDescription)
        }
        .sheet(item: savedRideBinding) { ride in
            RideSavedSheet(rideID: ride.id)
                .presentationDetents([.medium, .large])
        }
        .onAppear { recorder.warmUp() }
        .onDisappear { recorder.coolDown() }
    }

    @ViewBuilder private var backdrop: some View {
        if recorder.sport.usesGPS {
            RideMap(recorder: recorder)
        } else {
            TimerBackdrop(sport: recorder.sport)
        }
    }

    private var panel: some View {
        VStack(spacing: 12) {
            if let recovered = recorder.recovered, !recorder.isRecording {
                RecoveredBanner(start: recovered.start, sport: recovered.sport, save: { save(recovered: true) },
                                discard: recorder.discardRecovered)
            }
            if let watchError = watch.lastError {
                Label("A ride from your Watch couldn't be saved: \(watchError.localizedDescription)", systemImage: "applewatch.slash")
                    .font(.caption)
                    .padding(10)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
            }
            if session.pairing == nil {
                Label("Not paired with a server. This ride stays on the phone until you pair again.", systemImage: "link.badge.plus")
                    .font(.caption)
                    .padding(10)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
            }
            if recorder.isRecording {
                RideStatsPanel(recorder: recorder, units: session.units)
            }
            RecordControls(recorder: recorder, bikes: session.bikes, onStart: startRide) { confirmFinish = true }
        }
    }

    private var title: String {
        switch recorder.state {
        case .idle: "Record"
        case .recording: "Recording"
        case .paused: "Paused"
        }
    }

    private var savedRideBinding: Binding<SavedRide?> {
        Binding(get: { justSaved.flatMap { id in store.rides.first { $0.id == id } } },
                set: { justSaved = $0?.id })
    }

    /// An unsaved recovered ride is saved first, since starting a ride replaces the journal it lives in.
    /// If it can't be saved, the error shows and the new ride doesn't start.
    private func startRide() {
        if recorder.recovered != nil, !save(recovered: true, announce: false) { return }
        recorder.start(bike: Bike.pick(recorder.chosenBike, from: session.bikes))
    }

    /// Store the finished (or recovered) ride, then upload it. The recorder lets go of the ride only once it's
    /// on disk, so a failure is shown and nothing is thrown away. Returns whether it was stored.
    @discardableResult
    private func save(recovered: Bool, announce: Bool = true) -> Bool {
        let keep = { (gpx: Data?, summary: RideSummary) throws(AppError) -> SavedRide in
            if let gpx { return try store.add(gpx: gpx, summary: summary, source: .phone) }
            return try store.addSession(summary: summary, source: .phone)
        }
        do throws(AppError) {
            let ride = recovered ? try recorder.saveRecovered(into: keep) : try recorder.finish(into: keep)
            if announce { justSaved = ride.id }
            Task { await store.uploadPending(using: session) }
            return true
        } catch {
            self.error = error
            return false
        }
    }
}

/// The map: your position, plus the ride's track while recording (thinned on long rides so the map stays smooth).
private struct RideMap: View {
    var recorder: PhoneRideRecorder
    @State private var camera: MapCameraPosition = .userLocation(fallback: .automatic)

    var body: some View {
        Map(position: $camera) {
            UserAnnotation()
            if routeCoordinates.count > 1 {
                MapPolyline(coordinates: routeCoordinates)
                    .stroke(Color.accentColor, style: StrokeStyle(lineWidth: 5, lineCap: .round, lineJoin: .round))
            }
        }
        .mapControls {
            MapUserLocationButton()
            MapCompass()
        }
    }

    private var routeCoordinates: [CLLocationCoordinate2D] {
        guard recorder.isRecording else { return [] }
        let points = recorder.tracker.points
        let step = max(1, points.count / 2000)
        return stride(from: 0, to: points.count, by: step).map { points[$0].coordinate }
    }
}

/// Behind a timed session's clock, where the map would be: the sport's figure, large and faint.
private struct TimerBackdrop: View {
    var sport: Sport

    var body: some View {
        ZStack {
            Color(.systemGroupedBackground)
            Image(systemName: sport.systemImage)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 220, maxHeight: 220)
                .foregroundStyle(Color.accentColor.opacity(0.12))
                .accessibilityHidden(true)
        }
        .ignoresSafeArea(edges: .bottom)
    }
}
