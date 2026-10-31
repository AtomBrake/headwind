import PhotosUI
import SwiftUI

/// Everything recorded on this phone or the Watch, with its upload status. Swipe to delete; failed uploads retry.
/// A ride's bike can be changed from its menu, before or after it's uploaded, and photos added: they wait on the phone with the ride
/// and go up once it's on the server, never holding the ride up.
struct RecordingsView: View {
    @Environment(Session.self) private var session
    @Environment(RideStore.self) private var store
    @State private var error: AppError?
    @State private var photosFor: SavedRide?
    @State private var picked: [PhotosPickerItem] = []

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
                        .disabled(ride.status == .uploading)
                    }
                    if ride.status == .rejected {
                        Button { Task { await store.retry(ride, using: session) } } label: {
                            Label("Try uploading again", systemImage: "arrow.clockwise")
                        }
                    }
                    Button { photosFor = ride } label: { Label("Add photos", systemImage: "photo.badge.plus") }
                        .disabled(ride.status == .rejected)
                    if let gpx = store.gpxURL(for: ride) {
                        ShareLink(item: gpx) { Label("Share GPX", systemImage: "square.and.arrow.up") }
                    }
                }
            }
        }
        .navigationTitle("Recordings")
        .toolbar {
            if store.rides.contains(where: { $0.status == .failed || $0.status == .pending }) {
                Button("Upload") { Task { await store.uploadPending(using: session) } }
            }
        }
        .refreshable { await store.uploadPending(using: session) }
        .photosPicker(isPresented: Binding(get: { photosFor != nil }, set: { if !$0 && picked.isEmpty { photosFor = nil } }),
                      selection: $picked, maxSelectionCount: 10, matching: .images, photoLibrary: .shared())
        .onChange(of: picked) { _, items in
            guard !items.isEmpty, let ride = photosFor else { return }
            picked = []
            photosFor = nil
            Task { await addPhotos(items, to: ride) }
        }
        .alert("Something went wrong", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
               presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { error in
            Text(error.localizedDescription)
        }
    }

    /// Each picture shrunk to a JPEG and kept with the ride (RideStore.addPhoto), which sends it once the ride is on the server.
    private func addPhotos(_ items: [PhotosPickerItem], to ride: SavedRide) async {
        for item in items {
            guard let raw = try? await item.loadTransferable(type: Data.self), let jpeg = PhotoPrep.jpeg(from: raw) else {
                error = .validationError(message: "That picture couldn't be read.")
                continue
            }
            do throws(AppError) {
                try await store.addPhoto(jpeg, to: ride, using: session)
            } catch {
                self.error = error
            }
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
