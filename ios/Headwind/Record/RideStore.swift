import Foundation
import Observation
import UIKit

/// A finished recording kept on the phone: its GPX (none for a timed-only session), headline numbers (with its sport and bike), where it came
/// from, whether it reached the server, and photos waiting to go up with it.
struct SavedRide: Codable, Identifiable, Equatable {
    enum Source: String, Codable { case phone, watch }
    /// `rejected`: the server refused the recording itself (it can't read it, or it's too large), so it isn't retried by itself.
    enum Status: String, Codable { case pending, uploading, uploaded, failed, rejected }

    var id: UUID
    var summary: RideSummary
    var source: Source
    var status: Status
    /// Why the last upload failed, or the server's note (e.g. "Already on the server").
    var message: String?
    /// Activity id on the server once uploaded, and its kind there ('ride' or 'workout').
    var serverId: String?
    var serverKind: String?
    /// Photos added on the phone that haven't reached the server yet (file names in RideStore's photo folder for this ride).
    var pendingPhotos: [String]?

    init(id: UUID, summary: RideSummary, source: Source, status: Status, message: String? = nil, serverId: String? = nil) {
        self.id = id
        self.summary = summary
        self.source = source
        self.status = status
        self.message = message
        self.serverId = serverId
    }

    var name: String { GPXWriter.rideName(summary) }
    var filename: String { "\(id.uuidString).gpx" }
    /// A GPS recording has a GPX file; a timed-only session is its summary alone.
    var hasTrack: Bool { summary.sport.usesGPS }
    var kind: String { Uploader.kind(of: summary, reply: serverKind) }
}

/// Every finished ride is written here first, then uploaded. Uploads that fail (offline, server down) stay
/// pending and are retried when the app comes back to the foreground or another ride finishes. Ride uploads
/// are idempotent on the server (content-addressed id + near-duplicate guard; client_id for the rest), so a retry after a dropped
/// reply can't create a second copy.
@MainActor
@Observable
final class RideStore {
    private(set) var rides: [SavedRide] = []
    private let directory: URL
    private var uploading = false
    /// Set when uploadPending is called mid-upload, so the running pass goes round again for new rides.
    private var uploadAgain = false
    private var backgroundTask: UIBackgroundTaskIdentifier = .invalid

    init(directory: URL? = nil) {
        let base = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        self.directory = directory ?? base.appending(path: "Recordings", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: self.directory, withIntermediateDirectories: true)
        load()
    }

    var pendingCount: Int { rides.filter { $0.status != .uploaded && $0.status != .rejected }.count }

    @discardableResult
    func add(gpx: Data, summary: RideSummary, source: SavedRide.Source) throws(AppError) -> SavedRide {
        let ride = SavedRide(id: UUID(), summary: summary, source: source, status: .pending)
        do {
            try gpx.write(to: fileURL(ride), options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
        do throws(AppError) {
            try insert(ride)
        } catch {
            try? FileManager.default.removeItem(at: fileURL(ride))
            throw error
        }
        return ride
    }

    /// A timed-only session (strength, an indoor ride, a pool swim from the Watch): nothing but its summary. `id` is the Watch's own for one
    /// that came from there, so its direct upload and this one are the same recording to the server.
    @discardableResult
    func addSession(summary: RideSummary, source: SavedRide.Source, id: UUID = UUID()) throws(AppError) -> SavedRide {
        if let existing = rides.first(where: { $0.id == id }) { return existing }
        let ride = SavedRide(id: id, summary: summary, source: source, status: .pending)
        try insert(ride)
        return ride
    }

    /// Takes ownership of a GPX file (moved, not copied), e.g. one that arrived from the Watch. If it can't be
    /// stored, the file is left where it was. A ride already here under the same id (sent twice) keeps the first copy.
    @discardableResult
    func adopt(file: URL, summary: RideSummary, source: SavedRide.Source, id: UUID = UUID()) throws(AppError) -> SavedRide {
        if let existing = rides.first(where: { $0.id == id }) {
            try? FileManager.default.removeItem(at: file)
            return existing
        }
        let ride = SavedRide(id: id, summary: summary, source: source, status: .pending)
        do {
            try FileManager.default.moveItem(at: file, to: fileURL(ride))
        } catch {
            throw .storage(underlying: error)
        }
        do throws(AppError) {
            try insert(ride)
        } catch {
            try? FileManager.default.moveItem(at: fileURL(ride), to: file)
            throw error
        }
        return ride
    }

    /// A ride missing from the index would be orphaned on the next launch, so a failed index write undoes the insert.
    private func insert(_ ride: SavedRide) throws(AppError) {
        rides.insert(ride, at: 0)
        rides.sort { $0.summary.start > $1.summary.start }
        do throws(AppError) {
            try save()
        } catch {
            rides.removeAll { $0.id == ride.id }
            throw error
        }
    }

    func delete(_ ride: SavedRide) {
        try? FileManager.default.removeItem(at: fileURL(ride))
        try? FileManager.default.removeItem(at: photoFolder(ride.id))
        rides.removeAll { $0.id == ride.id }
        try? save()
    }

    /// The GPX to share, or nil for a timed-only session, which has none.
    func gpxURL(for ride: SavedRide) -> URL? { ride.hasTrack ? fileURL(ride) : nil }

    // MARK: - Photos

    /// Keep a photo (already a shrunk JPEG: see PhotoPrep) with the ride, to go up once the ride is on the server. Never holds the ride up.
    func addPhoto(_ jpeg: Data, to ride: SavedRide, using session: Session) async throws(AppError) {
        let folder = photoFolder(ride.id)
        let name = "\(UUID().uuidString).jpg"
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try jpeg.write(to: folder.appending(path: name), options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
        update(ride.id) { $0.pendingPhotos = ($0.pendingPhotos ?? []) + [name] }
        if let latest = rides.first(where: { $0.id == ride.id }), latest.status == .uploaded {
            await uploadPhotos(of: latest, using: session)
        }
    }

    /// Each waiting photo of an uploaded ride, one request each. One that fails stays for the next pass; one the server refuses is dropped.
    private func uploadPhotos(of ride: SavedRide, using session: Session) async {
        guard let serverId = ride.serverId, let names = ride.pendingPhotos, !names.isEmpty else { return }
        let folder = photoFolder(ride.id)
        for name in names {
            guard !Task.isCancelled else { return }
            let file = folder.appending(path: name)
            guard let data = try? Data(contentsOf: file) else {
                update(ride.id) { $0.pendingPhotos?.removeAll { $0 == name } }
                continue
            }
            do throws(AppError) {
                _ = try await session.call { client async throws(AppError) in
                    try await client.upload("rides/\(ride.kind)/\(serverId)/photos", file: data, filename: name, mimeType: "image/jpeg",
                                            fields: ["client_id": String(name.dropLast(4))], as: Ignored.self)
                }
            } catch {
                // Offline or the server down: the rest wait for the next pass. Unreadable, too many, or the activity gone: drop it.
                guard error.isRejection || error.isNotFound else { return }
            }
            try? FileManager.default.removeItem(at: file)
            update(ride.id) { $0.pendingPhotos?.removeAll { $0 == name } }
        }
    }

    func pendingPhotoURLs(for ride: SavedRide) -> [URL] {
        (ride.pendingPhotos ?? []).map { photoFolder(ride.id).appending(path: $0) }
    }

    private func photoFolder(_ id: UUID) -> URL { directory.appending(path: "Photos", directoryHint: .isDirectory).appending(path: id.uuidString) }

    // MARK: - Upload

    /// Upload everything not yet on the server, oldest first, then any photos waiting. Safe to call often: a call made mid-upload
    /// returns at once, and the running upload picks up any ride added since it started.
    func uploadPending(using session: Session) async {
        guard session.pairing != nil else { return }
        guard !uploading else { uploadAgain = true; return }
        uploading = true
        defer { uploading = false }

        // Finish even if the user locks the phone straight after stopping a ride. If iOS runs out of background
        // time first, stop: the ride in flight goes back to pending and the rest wait for the next foreground.
        let work = Task { await uploadAll(using: session) }
        backgroundTask = UIApplication.shared.beginBackgroundTask(withName: "Upload rides") { [weak self] in
            MainActor.assumeIsolated {
                work.cancel()
                self?.endBackgroundTask()
            }
        }
        await withTaskCancellationHandler { await work.value } onCancel: { work.cancel() }
        endBackgroundTask()
    }

    private func endBackgroundTask() {
        guard backgroundTask != .invalid else { return }
        UIApplication.shared.endBackgroundTask(backgroundTask)
        backgroundTask = .invalid
    }

    private func uploadAll(using session: Session) async {
        var tried = Set<UUID>()
        repeat {
            uploadAgain = false
            for ride in rides.reversed() where (ride.status == .pending || ride.status == .failed) && !tried.contains(ride.id) {
                guard !Task.isCancelled else { return }
                tried.insert(ride.id)
                guard await upload(ride, using: session) else { return }   // offline: don't burn through the rest
            }
        } while uploadAgain && !Task.isCancelled
        for ride in rides where ride.status == .uploaded && !(ride.pendingPhotos ?? []).isEmpty {
            guard !Task.isCancelled else { return }
            await uploadPhotos(of: ride, using: session)
        }
    }

    /// Returns false if the phone looks offline or the upload was cancelled, so the caller stops.
    private func upload(_ queued: SavedRide, using session: Session) async -> Bool {
        let ride = rides.first { $0.id == queued.id } ?? queued   // the latest copy: its bike may have changed since the pass began
        var gpx: Data?
        if ride.hasTrack {
            guard let data = try? Data(contentsOf: fileURL(ride)) else {
                update(ride.id) { $0.status = .failed; $0.message = "The recording file is missing." }
                return true
            }
            gpx = data
        }
        update(ride.id) { $0.status = .uploading; $0.message = nil }
        do throws(AppError) {
            let reply = try await session.call { [gpx] client async throws(AppError) in
                try await Uploader.upload(summary: ride.summary, id: ride.id, name: ride.name, gpx: gpx, with: client)
            }
            update(ride.id) {
                $0.status = .uploaded
                $0.serverId = reply.serverId
                $0.serverKind = reply.kind
                $0.message = reply.isNew ? nil : "Already on the server"
            }
            return true
        } catch {
            if Task.isCancelled {
                update(ride.id) { $0.status = .pending; $0.message = nil }
                return false
            }
            update(ride.id) { $0.status = error.isRejection ? .rejected : .failed; $0.message = error.localizedDescription }
            return !error.isNetworkError
        }
    }

    /// Where a recording goes (Uploader.destination), kept here for the tests.
    nonisolated static func destination(_ ride: SavedRide) -> (path: String, fields: [String: String]) {
        Uploader.destination(summary: ride.summary, id: ride.id, name: ride.name)
    }

    /// Put a ride on another bike. Before upload it's only noted here and goes up with the ride; after, the server is told
    /// first (POST /api/v1/rides/ride/<id>/bike) and the phone's copy changes only once it agrees.
    func setBike(_ bike: Int?, for ride: SavedRide, using session: Session) async throws(AppError) {
        guard ride.summary.sport.isRide else { return }
        switch ride.status {
        case .uploaded:
            guard let serverId = ride.serverId else {
                throw .validationError(message: "Headwind didn't say which ride this became. Change its bike on the ride's page.")
            }
            _ = try await session.call { client async throws(AppError) in
                try await client.post("rides/ride/\(serverId)/bike", json: BikeChange(bike_id: bike), as: Ignored.self)
            }
        case .uploading:
            throw .validationError(message: "This ride is uploading. Change its bike once it's on the server.")
        case .pending, .failed, .rejected:
            break
        }
        update(ride.id) { $0.summary.bikeId = bike }
    }

    /// Try a refused upload again, e.g. after the server was updated to read it.
    func retry(_ ride: SavedRide, using session: Session) async {
        update(ride.id) { $0.status = .pending; $0.message = nil }
        await uploadPending(using: session)
    }

    private func update(_ id: UUID, _ change: (inout SavedRide) -> Void) {
        guard let i = rides.firstIndex(where: { $0.id == id }) else { return }
        change(&rides[i])
        try? save()
    }

    private func fileURL(_ ride: SavedRide) -> URL { directory.appending(path: ride.filename) }
    private var indexURL: URL { directory.appending(path: "index.json") }

    private func load() {
        guard let data = try? Data(contentsOf: indexURL),
              let saved = try? JSONDecoder().decode([SavedRide].self, from: data) else { return }
        // An upload interrupted by the app being killed is just pending again.
        rides = saved.map { var r = $0; if r.status == .uploading { r.status = .pending }; return r }
    }

    private func save() throws(AppError) {
        do {
            try JSONEncoder().encode(rides).write(to: indexURL, options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
    }
}

/// Body of POST /api/v1/rides/ride/<id>/bike; a nil bike_id is sent as null (no bike).
private struct BikeChange: Encodable, Sendable {
    var bike_id: Int?

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(bike_id, forKey: .bike_id)
    }

    private enum CodingKeys: String, CodingKey { case bike_id }
}
