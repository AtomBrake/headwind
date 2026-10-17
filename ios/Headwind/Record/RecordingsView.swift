import SwiftUI

/// Every ride recorded on this phone or the Watch, with its upload status. Swipe to delete; failed uploads retry.
struct RecordingsView: View {
    @Environment(Session.self) private var session
    @Environment(RideStore.self) private var store

    var body: some View {
        List {
            if store.rides.isEmpty {
                ContentUnavailableView("No recordings yet", systemImage: "bicycle",
                                       description: Text("Rides you record on this iPhone or your Apple Watch appear here."))
            }
            ForEach(store.rides) { ride in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Image(systemName: ride.source == .watch ? "applewatch" : "iphone")
                            .foregroundStyle(.secondary)
                        Text(GPXWriter.rideName(start: ride.summary.start)).font(.headline)
                        Spacer()
                        Text(ride.summary.start.formatted(date: .abbreviated, time: .shortened))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Text([session.units.distance(metres: ride.summary.distance),
                          Units.duration(seconds: ride.summary.movingTime),
                          session.units.elevation(metres: ride.summary.elevationGain)].joined(separator: " · "))
                        .font(.subheadline)
                        .monospacedDigit()
                    UploadStatusLabel(ride: ride).font(.caption)
                }
                .padding(.vertical, 2)
                .swipeActions {
                    Button("Delete", role: .destructive) { store.delete(ride) }
                }
                .contextMenu {
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
    }
}
