import SwiftUI

/// Everything recorded on this phone or the Watch, with its upload status. Swipe to delete; failed uploads retry.
/// A ride's bike can be changed from its menu, before or after it's uploaded.
struct RecordingsView: View {
    @Environment(Session.self) private var session
    @Environment(RideStore.self) private var store
    @State private var error: AppError?

    var body: some View {
        List {
            if store.rides.isEmpty {
                ContentUnavailableView("No recordings yet", systemImage: "bicycle",
                                       description: Text("Rides, runs and walks you record on this iPhone or your Apple Watch appear here."))
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
                    ShareLink(item: store.gpxURL(for: ride)) { Label("Share GPX", systemImage: "square.and.arrow.up") }
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
        .alert("Couldn't change the bike", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
               presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { error in
            Text(error.localizedDescription)
        }
    }

    /// Distance, time and climbing, and the bike for a ride when one was chosen (otherwise the server gives it the default).
    private func details(_ ride: SavedRide) -> [String] {
        var parts = [session.units.distance(metres: ride.summary.distance),
                     Units.duration(seconds: ride.summary.movingTime),
                     session.units.elevation(metres: ride.summary.elevationGain)]
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
