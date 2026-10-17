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
    @State private var confirmFinish = false
    @State private var justSaved: SavedRide.ID?
    @State private var error: AppError?

    var body: some View {
        ZStack(alignment: .bottom) {
            RideMap(recorder: recorder)

            VStack(spacing: 12) {
                if let recovered = recorder.recovered, !recorder.isRecording {
                    RecoveredBanner(start: recovered.start, save: saveRecovered, discard: recorder.discardRecovered)
                }
                if let watchError = watch.lastError {
                    Label("A ride from your Watch couldn't be saved: \(watchError.localizedDescription)", systemImage: "applewatch.slash")
                        .font(.caption)
                        .padding(10)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                }
                if recorder.isRecording {
                    RideStatsPanel(recorder: recorder, units: session.units)
                }
                RecordControls(recorder: recorder) { confirmFinish = true }
            }
            .padding(16)
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { router.show(.recordings) } label: {
                    Label("Recordings", systemImage: "list.bullet")
                }
                .badge(store.pendingCount)
                .accessibilityIdentifier("recordings")
            }
        }
        .confirmationDialog("Finish this ride?", isPresented: $confirmFinish, titleVisibility: .visible) {
            Button("Save ride") { save(recorder.finish) }
            Button("Discard ride", role: .destructive) { recorder.discard() }
            Button("Keep riding", role: .cancel) {}
        }
        .alert("Couldn't save the ride", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
               presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { error in
            Text(error.localizedDescription)
        }
        .sheet(item: savedRideBinding) { ride in
            RideSavedSheet(rideID: ride.id)
                .presentationDetents([.medium])
        }
        .onAppear { recorder.warmUp() }
        .onDisappear { recorder.coolDown() }
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

    private func saveRecovered() { save(recorder.takeRecovered) }

    /// Store the finished ride, then upload it. Any failure is shown and nothing is thrown away.
    private func save(_ take: () throws(AppError) -> (gpx: Data, summary: RideSummary)) {
        do throws(AppError) {
            let (gpx, summary) = try take()
            justSaved = try store.add(gpx: gpx, summary: summary, source: .phone).id
            Task { await store.uploadPending(using: session) }
        } catch {
            self.error = error
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
