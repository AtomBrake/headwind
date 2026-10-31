import PhotosUI
import SwiftUI

/// A recording's photos still on the phone (SavedRide.pendingPhotos): add more from the library or the camera, remove them, and put them in
/// order, which is the order they go up in and so their order on the server. Once one is up it's on the activity's page under Activities.
struct PendingPhotosView: View {
    var rideID: UUID
    @Environment(Session.self) private var session
    @Environment(RideStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var picked: [PhotosPickerItem] = []
    @State private var camera = false
    @State private var error: AppError?

    private var ride: SavedRide? { store.rides.first { $0.id == rideID } }

    var body: some View {
        NavigationStack {
            List {
                if let ride {
                    let names = ride.pendingPhotos ?? []
                    Section {
                        if names.isEmpty {
                            Text("No photos waiting.").foregroundStyle(.secondary)
                        }
                        ForEach(Array(names.enumerated()), id: \.element) { n, name in
                            row(name, number: n + 1, of: ride)
                                .deleteDisabled(store.sendingPhoto[ride.id] == name)
                        }
                        .onDelete { offsets in
                            for name in offsets.map({ names[$0] }) { store.removePendingPhoto(name, from: ride) }
                        }
                        .onMove { store.movePendingPhotos(of: ride, from: $0, to: $1) }
                    } footer: {
                        Text(ride.status == .uploaded
                             ? "They go up one at a time, in this order. Ones already up are on the activity's page under Activities."
                             : "They go up in this order once the recording is on the server.")
                    }
                    Section {
                        PhotosPicker(selection: $picked, maxSelectionCount: 10, matching: .images, photoLibrary: .shared()) {
                            Label("Add photos", systemImage: "photo.badge.plus")
                        }
                        if CameraPicker.isAvailable {
                            Button { camera = true } label: { Label("Take a photo", systemImage: "camera") }
                        }
                    }
                    .disabled(ride.status == .rejected)
                }
            }
            .navigationTitle("Photos")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                if (ride?.pendingPhotos?.count ?? 0) > 1 { ToolbarItem(placement: .topBarLeading) { EditButton() } }
            }
            .onChange(of: picked) { _, items in
                guard !items.isEmpty else { return }
                picked = []
                Task { await add(items) }
            }
            .fullScreenCover(isPresented: $camera) {
                CameraPicker { image in
                    camera = false
                    if let image, let jpeg = PhotoPrep.jpeg(from: image) { Task { await keep(jpeg) } }
                }
                .ignoresSafeArea()
            }
            .alert("Something went wrong", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }), presenting: error) { _ in
                Button("OK", role: .cancel) {}
            } message: { error in
                Text(error.localizedDescription)
            }
        }
    }

    private func row(_ name: String, number: Int, of ride: SavedRide) -> some View {
        HStack(spacing: 12) {
            LocalThumb(url: store.pendingPhotoURL(name, of: ride))
                .frame(width: 56, height: 56)
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading) {
                Text(number == 1 ? "Photo 1 · cover" : "Photo \(number)")
                if store.sendingPhoto[ride.id] == name {
                    Text("Uploading…").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    /// Each picture shrunk to a JPEG and kept with the ride (RideStore.addPhoto), which sends it once the ride is on the server.
    private func add(_ items: [PhotosPickerItem]) async {
        for item in items {
            guard let raw = try? await item.loadTransferable(type: Data.self), let jpeg = PhotoPrep.jpeg(from: raw) else {
                error = .validationError(message: "That picture couldn't be read.")
                continue
            }
            await keep(jpeg)
        }
    }

    private func keep(_ jpeg: Data) async {
        guard let ride else { return }
        do throws(AppError) {
            try await store.addPhoto(jpeg, to: ride, using: session)
        } catch {
            self.error = error
        }
    }
}

/// A photo file on the phone, drawn small.
private struct LocalThumb: View {
    var url: URL
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                Color(.secondarySystemFill)
            }
        }
        .task(id: url) {
            image = await Task.detached { UIImage(contentsOfFile: url.path)?.preparingThumbnail(of: CGSize(width: 168, height: 168)) }.value
        }
    }
}
