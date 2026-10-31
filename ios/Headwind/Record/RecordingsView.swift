import SwiftUI

/// Everything recorded on this phone or the Watch, with its upload status. Swipe to delete; failed uploads retry.
/// A ride's bike can be changed from its menu, before or after it's uploaded, and photos added, removed and put in order (PendingPhotosView):
/// they wait on the phone with the ride and go up once it's on the server, never holding the ride up. A recording made under another server
/// waits for it, unless it's sent to this one from its menu.
struct RecordingsView: View {
    @Environment(Session.self) private var session
    @Environment(RideStore.self) private var store
    @State private var error: AppError?
    @State private var photosFor: SavedRide?

    var body: some View {
        List {
            if store.rides.isEmpty {
                ContentUnavailableView("No recordings yet", systemImage: "figure.mixed.cardio",
                                       description: Text("Rides, runs, swims and sessions you record on this iPhone or your Apple Watch appear here."))
            }
            ForEach(store.rides) { ride in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Image(systemName: ride.summary.sport.systemImage)
                            .foregroundStyle(.secondary)
                            .accessibilityLabel(ride.summary.sport.title)
                        Text(ride.name).font(.headline)
                        Image(systemName: ride.source == .watch ? "applewatch" : "iphone")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                        Spacer()
                        Text(ride.summary.start.formatted(date: .abbreviated, time: .shortened))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text(details(ride).joined(separator: " · "))
                        .font(.subheadline)
                        .monospacedDigit()
                    UploadStatusLabel(ride: ride).font(.caption)
                    if let waiting = ride.pendingPhotos, !waiting.isEmpty {
                        Label("\(waiting.count) photo\(waiting.count == 1 ? "" : "s") to upload", systemImage: "photo")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 2)
                .swipeActions {
                    Button("Delete", role: .destructive) { store.delete(ride) }
                }
                .contextMenu {
                    let here = ride.belongs(to: session.pairing?.server)
                    if ride.summary.sport.isRide, !session.bikes.isEmpty {
                        Menu {
                            ForEach(session.bikes) { bike in
                                Button {
                                    change(ride, to: bike.id)
                                } label: {
                                    if ride.summary.bikeId == bike.id { Label(bike.name, systemImage: "checkmark") } else { Text(bike.name) }
                                }
                            }
                        } label: {
                            Label("Bike", systemImage: "bicycle")
                        }
                        .disabled(ride.status == .uploading || (ride.status == .uploaded && !here))
                    }
                    if !here, ride.status != .uploaded, ride.status != .uploading, let host = session.pairing?.server.host() {
                        Button { Task { await store.send(ride, toCurrentServerUsing: session) } } label: {
                            Label("Upload to \(host) instead", systemImage: "arrow.up.circle")
                        }
                    }
                    if ride.status == .rejected, here {
                        Button { Task { await store.retry(ride, using: session) } } label: {
                            Label("Try uploading again", systemImage: "arrow.clockwise")
                        }
                    }
                    Button { photosFor = ride } label: {
                        let waiting = ride.pendingPhotos?.count ?? 0
                        Label(waiting == 0 ? "Add photos" : "Photos (\(waiting) waiting)", systemImage: "photo.badge.plus")
                    }
                    .disabled((ride.status == .rejected || (ride.status == .uploaded && !here)) && (ride.pendingPhotos ?? []).isEmpty)
                    if let gpx = store.gpxURL(for: ride) {
                        ShareLink(item: gpx) { Label("Share GPX", systemImage: "square.and.arrow.up") }
                    }
                }
            }
        }
        .navigationTitle("Recordings")
        .toolbar {
            if let server = session.pairing?.server, store.waitingCount(for: server) > 0 {
                Button("Upload") { Task { await store.uploadPending(using: session) } }
            }
        }
        .refreshable { await store.uploadPending(using: session) }
        .sheet(item: $photosFor) { ride in PendingPhotosView(rideID: ride.id) }
        .alert("Something went wrong", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
               presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { error in
            Text(error.localizedDescription)
        }
    }

    /// Distance, time and climbing (a timed session's time alone, with what the Watch measured), and the bike for a ride when one was
    /// chosen (otherwise the server gives it the default).
    private func details(_ ride: SavedRide) -> [String] {
        let s = ride.summary
        var parts: [String] = []
        if s.sport.hasDistance, s.distance > 0 { parts.append(session.units.distance(metres: s.distance, sport: s.sport)) }
        parts.append(Units.duration(seconds: s.movingTime))
        if s.sport.usesGPS, !s.sport.isSwim { parts.append(session.units.elevation(metres: s.elevationGain)) }
        if !s.sport.usesGPS, let kcal = s.calories { parts.append("\(Units.whole(kcal)) kcal") }
        if let id = ride.summary.bikeId, let bike = session.bikes.first(where: { $0.id == id }) {
            parts.append(bike.name)
        }
        return parts
    }

    private func change(_ ride: SavedRide, to bike: Int) {
        Task {
            do throws(AppError) {
                try await store.setBike(bike, for: ride, using: session)
            } catch {
                self.error = error
            }
        }
    }
}
