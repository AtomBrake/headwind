import PhotosUI
import SwiftUI
import UniformTypeIdentifiers

/// The server's reply to every photo change (add, delete, order, caption): the activity's photos as they now are.
struct PhotoList: Decodable, Sendable {
    var photos: [ActivityDetail.Photo]
}

/// One picture on its way to the server: a tile in the grid until it's there. A failed one stays, to be tried again or removed.
private struct PhotoUpload: Identifiable {
    enum State: Equatable { case preparing, waiting, sending, failed(String) }

    let id = UUID()
    var item: PhotosPickerItem?
    var jpeg: Data?
    var preview: UIImage?
    var state: State = .preparing
    /// The server's client_id, the same on every try, so a retry after a dropped reply isn't added twice.
    var clientID: String
}

/// An activity's photos (POST/DELETE/PATCH /api/v1/rides/<kind>/<id>/photos…). Added from the library (PhotosPicker, no permission needed) or the
/// camera, each with a tile of its own while it uploads, one at a time in the order picked. Select mode deletes several at once and drags to
/// reorder; the first photo is the activity's cover. A caption is set on the full-screen photo.
struct PhotosCard: View {
    /// e.g. "rides/ride/123/photos"
    var path: String
    @Binding var photos: [ActivityDetail.Photo]
    @Environment(Session.self) private var session
    @State private var uploads: [PhotoUpload] = []
    @State private var sending = false
    @State private var picked: [PhotosPickerItem] = []
    @State private var camera = false
    @State private var selecting = false
    @State private var selected: Set<Int> = []
    @State private var toDelete: [ActivityDetail.Photo] = []
    @State private var dragging: ActivityDetail.Photo?
    /// The order before this drag, to compare with once it ends and to put back if the server refuses.
    @State private var orderBefore: [ActivityDetail.Photo]?
    @State private var viewing: ActivityDetail.Photo?
    @State private var captioning: ActivityDetail.Photo?
    @State private var captionText = ""
    @State private var error: AppError?

    private let columns = [GridItem(.adaptive(minimum: 90), spacing: 6)]

    var body: some View {
        Card(title: "Photos") {
            if photos.isEmpty && uploads.isEmpty {
                Text("No photos yet.").foregroundStyle(.secondary)
            }
            grid
            if selecting { selectBar } else { addBar }
        }
        .onChange(of: picked) { _, items in
            guard !items.isEmpty else { return }
            picked = []
            add(items)
        }
        .fullScreenCover(isPresented: $camera) {
            CameraPicker { image in
                camera = false
                if let image { add(image) }
            }
            .ignoresSafeArea()
        }
        .sheet(item: $viewing) { photo in
            viewer(photo)
        }
        .modifier(CaptionEditor(captioning: captionHere(viewer: false), text: $captionText, save: saveCaption))
        .confirmationDialog(deleteTitle, isPresented: confirmingDelete, titleVisibility: .visible) {
            Button("Delete", role: .destructive) { deleteConfirmed() }
        } message: {
            Text(toDelete.count == 1 ? "It's removed from the server for good." : "They're removed from the server for good.")
        }
        .alert("Something went wrong", isPresented: showingError, presenting: error) { _ in
            Button("OK", role: .cancel) {}
        } message: { e in
            Text(e.localizedDescription)
        }
    }

    private func viewer(_ photo: ActivityDetail.Photo) -> some View {
        let current: ActivityDetail.Photo = photos.first { $0.id == photo.id } ?? photo
        return PhotoViewer(photo: current, caption: editCaption, delete: deleteFromViewer)
            .modifier(CaptionEditor(captioning: captionHere(viewer: true), text: $captionText, save: saveCaption))
    }

    /// The caption alert shows over the full-screen photo when that's open, otherwise over the card: never both.
    private func captionHere(viewer: Bool) -> Binding<ActivityDetail.Photo?> {
        (viewing != nil) == viewer ? $captioning : .constant(nil)
    }

    private var deleteTitle: String { toDelete.count == 1 ? "Delete this photo?" : "Delete \(toDelete.count) photos?" }
    private var confirmingDelete: Binding<Bool> { Binding(get: { !toDelete.isEmpty }, set: { if !$0 { toDelete = [] } }) }
    private var showingError: Binding<Bool> { Binding(get: { error != nil }, set: { if !$0 { error = nil } }) }

    private func editCaption(_ photo: ActivityDetail.Photo) {
        captionText = photo.caption ?? ""
        captioning = photo
    }

    private func deleteFromViewer(_ photo: ActivityDetail.Photo) {
        viewing = nil
        Task { await delete([photo]) }
    }

    private func deleteConfirmed() {
        let these = toDelete
        Task { await delete(these) }
    }

    private var grid: some View {
        LazyVGrid(columns: columns, spacing: 6) {
            ForEach(photos) { photo in
                tile(photo)
            }
            ForEach(uploads) { upload in
                UploadTile(upload: upload, retry: { retry(upload) }, remove: { uploads.removeAll { $0.id == upload.id } })
            }
        }
        .onDrop(of: [.text], delegate: ReorderDrop(target: nil, photos: $photos, dragging: $dragging, commit: commitOrder))
    }

    @ViewBuilder
    private var selectBar: some View {
        Text("Tap photos to select them. Hold one and drag it to move it; the first is the cover.")
            .font(.caption)
            .foregroundStyle(.secondary)
        HStack {
            Button(selected.isEmpty ? "Delete" : "Delete (\(selected.count))", systemImage: "trash", role: .destructive) {
                toDelete = photos.filter { selected.contains($0.id) }
            }
            .disabled(selected.isEmpty)
            Spacer()
            Button("Done") { endSelecting() }.bold()
        }
    }

    private var addBar: some View {
        HStack(spacing: 20) {
            PhotosPicker(selection: $picked, maxSelectionCount: 10, matching: .images, photoLibrary: .shared()) {
                Label("Add photos", systemImage: "photo.badge.plus")
            }
            if CameraPicker.isAvailable {
                Button { camera = true } label: { Label("Camera", systemImage: "camera") }
            }
            Spacer()
            if !photos.isEmpty {
                Button("Select") { selecting = true }
                    .disabled(!uploads.isEmpty)     // an order sent mid-upload would miss the new photo and be refused
            }
        }
    }

    @ViewBuilder
    private func tile(_ photo: ActivityDetail.Photo) -> some View {
        let thumb = AuthedImage(path: photo.thumbUrl)
            .frame(minWidth: 90, minHeight: 90)
            .frame(maxWidth: .infinity)
            .aspectRatio(1, contentMode: .fit)
            .clipped()
            .clipShape(RoundedRectangle(cornerRadius: 8))
        if selecting {
            let on = selected.contains(photo.id)
            Button {
                if on { selected.remove(photo.id) } else { selected.insert(photo.id) }
            } label: {
                thumb
                    .opacity(dragging?.id == photo.id ? 0.4 : 1)
                    .overlay(alignment: .topTrailing) {
                        Image(systemName: on ? "checkmark.circle.fill" : "circle")
                            .font(.title3)
                            .symbolRenderingMode(.palette)
                            .foregroundStyle(.white, on ? Color.accentColor : .black.opacity(0.3))
                            .padding(4)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(photo.caption ?? "Photo")
            .accessibilityAddTraits(on ? .isSelected : [])
            .onDrag {
                if orderBefore == nil { orderBefore = photos }
                dragging = photo
                return NSItemProvider(object: String(photo.id) as NSString)
            }
            .onDrop(of: [.text], delegate: ReorderDrop(target: photo, photos: $photos, dragging: $dragging, commit: commitOrder))
        } else {
            Button { viewing = photo } label: { thumb }
                .buttonStyle(.plain)
                .contextMenu {
                    Button(photo.caption == nil ? "Add caption" : "Edit caption", systemImage: "text.below.photo") { editCaption(photo) }
                    Button("Delete photo", systemImage: "trash", role: .destructive) { toDelete = [photo] }
                }
                .accessibilityLabel(photo.caption ?? "Photo")
        }
    }

    // MARK: - Adding

    /// A tile for each picked picture at once; each is shrunk to a JPEG in turn, then they go up in the order picked.
    private func add(_ items: [PhotosPickerItem]) {
        let added = items.map { PhotoUpload(item: $0, clientID: $0.itemIdentifier ?? UUID().uuidString) }
        uploads += added
        Task {
            for upload in added { await prepare(upload.id) }
        }
    }

    private func add(_ image: UIImage) {
        guard let jpeg = PhotoPrep.jpeg(from: image) else {
            error = .validationError(message: "That picture couldn't be read.")
            return
        }
        uploads.append(PhotoUpload(jpeg: jpeg, preview: UIImage(data: jpeg), state: .waiting, clientID: UUID().uuidString))
        Task { await pump() }
    }

    private func prepare(_ id: UUID) async {
        guard let item = uploads.first(where: { $0.id == id })?.item else { return }
        let raw = try? await item.loadTransferable(type: Data.self)
        let jpeg = raw.flatMap { PhotoPrep.jpeg(from: $0) }
        guard let i = uploads.firstIndex(where: { $0.id == id }) else { return }    // removed meanwhile
        uploads[i].jpeg = jpeg
        uploads[i].preview = jpeg.flatMap { UIImage(data: $0) }
        uploads[i].state = jpeg == nil ? .failed("That picture couldn't be read.") : .waiting
        await pump()
    }

    /// Send the waiting tiles one at a time, oldest first. A failure marks that tile and moves on; a tile still being prepared holds the
    /// rest back so they reach the server in the order picked.
    private func pump() async {
        guard !sending else { return }
        sending = true
        defer { sending = false }
        while let i = uploads.firstIndex(where: { if case .failed = $0.state { false } else { true } }) {
            guard uploads[i].state == .waiting, let jpeg = uploads[i].jpeg else { return }    // preparing: prepare() calls again
            let id = uploads[i].id, clientID = uploads[i].clientID
            uploads[i].state = .sending
            do throws(AppError) {
                let reply = try await session.call { client async throws(AppError) in
                    try await client.upload(path, file: jpeg, filename: "photo.jpg", mimeType: "image/jpeg", fields: ["client_id": clientID],
                                            as: PhotoList.self)
                }
                photos = reply.photos
                uploads.removeAll { $0.id == id }
            } catch {
                if let j = uploads.firstIndex(where: { $0.id == id }) { uploads[j].state = .failed(error.localizedDescription) }
            }
        }
    }

    private func retry(_ upload: PhotoUpload) {
        guard let i = uploads.firstIndex(where: { $0.id == upload.id }) else { return }
        if uploads[i].jpeg != nil {
            uploads[i].state = .waiting
            Task { await pump() }
        } else if uploads[i].item != nil {
            uploads[i].state = .preparing
            Task { await prepare(upload.id) }
        }
    }

    // MARK: - Deleting, ordering, captions

    /// One request per photo; a failure stops there and says so, and the grid shows what the server has.
    private func delete(_ these: [ActivityDetail.Photo]) async {
        for photo in these {
            do throws(AppError) {
                let reply = try await session.call { client async throws(AppError) in
                    try await client.delete("\(path)/\(photo.id)", as: PhotoList.self)
                }
                photos = reply.photos
                selected.remove(photo.id)
            } catch {
                if !error.isNotFound {      // already gone is what was wanted
                    self.error = error
                    return
                }
                photos.removeAll { $0.id == photo.id }
            }
        }
        if photos.isEmpty { endSelecting() }
    }

    /// The new order, once a drag ends (or on Done, for a drag dropped outside the grid), if it changed. Put back if the server refuses.
    private func commitOrder() {
        guard let before = orderBefore else { return }
        orderBefore = nil
        dragging = nil
        let ids = photos.map(\.id)
        guard ids != before.map(\.id) else { return }
        Task {
            do throws(AppError) {
                let reply = try await session.call { client async throws(AppError) in
                    try await client.post("\(path)/order", json: ["ids": ids], as: PhotoList.self)
                }
                photos = reply.photos
            } catch {
                photos = before
                self.error = error
            }
        }
    }

    private func endSelecting() {
        commitOrder()
        selecting = false
        selected = []
    }

    private func saveCaption(_ photo: ActivityDetail.Photo, _ text: String) {
        Task {
            do throws(AppError) {
                let reply = try await session.call { client async throws(AppError) in
                    try await client.patch("\(path)/\(photo.id)", json: ["caption": text], as: PhotoList.self)
                }
                photos = reply.photos
            } catch {
                self.error = error
            }
        }
    }
}

/// A picture on its way up: its preview, dimmed with a spinner while it waits or sends; a failed one says why, with Try again and Remove.
private struct UploadTile: View {
    var upload: PhotoUpload
    var retry: () -> Void
    var remove: () -> Void

    var body: some View {
        ZStack {
            if let preview = upload.preview {
                Image(uiImage: preview).resizable().scaledToFill()
            } else {
                Color(.secondarySystemFill)
            }
            if case .failed = upload.state {
                Color.black.opacity(0.45)
                Image(systemName: "exclamationmark.arrow.circlepath").font(.title2).foregroundStyle(.white)
            } else {
                Color.black.opacity(0.3)
                ProgressView().tint(.white)
            }
        }
        .frame(minWidth: 90, minHeight: 90)
        .frame(maxWidth: .infinity)
        .aspectRatio(1, contentMode: .fit)
        .clipped()
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .contentShape(Rectangle())
        .onTapGesture { if case .failed = upload.state { retry() } }
        .contextMenu {
            if case .failed(let why) = upload.state {
                Text(why)
                if upload.jpeg != nil || upload.item != nil {
                    Button("Try again", systemImage: "arrow.clockwise", action: retry)
                }
                Button("Remove", systemImage: "xmark", role: .destructive, action: remove)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label)
        .accessibilityAction(named: "Try again") { retry() }
    }

    private var label: String {
        switch upload.state {
        case .preparing, .waiting: "Photo waiting to upload"
        case .sending: "Photo uploading"
        case .failed(let why): "Photo not uploaded: \(why). Tap to try again."
        }
    }
}

/// Moves the dragged photo to where it's held over (`target`), live, and sends the new order when it's dropped: on a tile, or anywhere on the
/// grid (target nil).
private struct ReorderDrop: DropDelegate {
    var target: ActivityDetail.Photo?
    @Binding var photos: [ActivityDetail.Photo]
    @Binding var dragging: ActivityDetail.Photo?
    var commit: () -> Void

    func dropEntered(info: DropInfo) {
        guard let target, let dragging, dragging.id != target.id,
              let from = photos.firstIndex(where: { $0.id == dragging.id }), let to = photos.firstIndex(where: { $0.id == target.id }) else { return }
        withAnimation(.snappy) { photos.move(fromOffsets: IndexSet(integer: from), toOffset: to > from ? to + 1 : to) }
    }

    func dropUpdated(info: DropInfo) -> DropProposal? { DropProposal(operation: .move) }

    func validateDrop(info: DropInfo) -> Bool { dragging != nil }

    func performDrop(info: DropInfo) -> Bool {
        commit()
        return true
    }
}

/// The full-size photo with its caption under it, and Caption and Delete in the toolbar.
private struct PhotoViewer: View {
    var photo: ActivityDetail.Photo
    var caption: (ActivityDetail.Photo) -> Void
    var delete: (ActivityDetail.Photo) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var confirm = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                AuthedImage(path: photo.url, contentMode: .fit)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                if let text = photo.caption {
                    Text(text)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16)
                }
            }
            .padding(.bottom, 12)
            .navigationTitle("Photo")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItemGroup(placement: .bottomBar) {
                    Button(photo.caption == nil ? "Add caption" : "Edit caption", systemImage: "text.below.photo") { caption(photo) }
                    Spacer()
                    Button("Delete", systemImage: "trash", role: .destructive) { confirm = true }
                }
            }
            .confirmationDialog("Delete this photo?", isPresented: $confirm, titleVisibility: .visible) {
                Button("Delete", role: .destructive) { delete(photo) }
            } message: {
                Text("It's removed from the server for good.")
            }
        }
    }
}

/// An alert with a text field for a photo's caption; an empty one clears it.
private struct CaptionEditor: ViewModifier {
    @Binding var captioning: ActivityDetail.Photo?
    @Binding var text: String
    var save: (ActivityDetail.Photo, String) -> Void

    func body(content: Content) -> some View {
        content.alert("Caption", isPresented: Binding(get: { captioning != nil }, set: { if !$0 { captioning = nil } }), presenting: captioning) { photo in
            TextField("Caption", text: $text)
            Button("Save") { save(photo, String(text.prefix(200))) }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("Shown under the photo. Leave it empty for none.")
        }
    }
}
