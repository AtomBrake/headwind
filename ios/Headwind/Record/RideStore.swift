import Foundation
import Observation
import UIKit

/// A finished recording kept on the phone: its GPX, headline numbers (with its sport and bike), where it came from and
/// whether it reached the server.
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
    /// Activity id on the server once uploaded.
    var serverId: String?

    var name: String { GPXWriter.rideName(summary) }
    var filename: String { "\(id.uuidString).gpx" }
}

/// POST /api/v1/rides reply (routes/api_v1.py upload_ride), or /workouts (post_workout), whose activity is under `workout`.
private struct UploadReply: Decodable, Sendable {
    var status: String
    var ride: Ride?
    var workout: Ride?
    var serverId: String? { (ride ?? workout)?.id }
    /// /rides says "imported", /workouts "created"; anything else was already there.
    var isNew: Bool { status == "imported" || status == "created" }

    struct Ride: Decodable, Sendable {
        var id: String?

        /// The id is informational: accept a string or a number, and never fail the whole reply over it.
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            id = (try? c.decode(String.self, forKey: .id)) ?? (try? c.decode(Int.self, forKey: .id)).map(String.init)
        }

        private enum CodingKeys: String, CodingKey { case id }
    }
}

/// Every finished ride is written here first, then uploaded. Uploads that fail (offline, server down) stay
/// pending and are retried when the app comes back to the foreground or another ride finishes. Ride uploads
/// are idempotent on the server (content-addressed id + near-duplicate guard), so a retry after a dropped
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

    /// Takes ownership of a GPX file (moved, not copied), e.g. one that arrived from the Watch. If it can't be
    /// stored, the file is left where it was.
    @discardableResult
    func adopt(file: URL, summary: RideSummary, source: SavedRide.Source) throws(AppError) -> SavedRide {
        let ride = SavedRide(id: UUID(), summary: summary, source: source, status: .pending)
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
        rides.removeAll { $0.id == ride.id }
        try? save()
    }

    func gpxURL(for ride: SavedRide) -> URL { fileURL(ride) }

    /// Upload everything not yet on the server, oldest first. Safe to call often: a call made mid-upload
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
    }

    /// Returns false if the phone looks offline or the upload was cancelled, so the caller stops.
    private func upload(_ queued: SavedRide, using session: Session) async -> Bool {
        let ride = rides.first { $0.id == queued.id } ?? queued   // the latest copy: its bike may have changed since the pass began
        guard let data = try? Data(contentsOf: fileURL(ride)) else {
            update(ride.id) { $0.status = .failed; $0.message = "The recording file is missing." }
            return true
        }
        update(ride.id) { $0.status = .uploading; $0.message = nil }
        let (path, fields) = Self.destination(ride)
        do throws(AppError) {
            let reply = try await session.call { client async throws(AppError) in
                try await client.upload(path, file: data, filename: "\(ride.name).gpx", mimeType: "application/gpx+xml",
                                        fields: fields, as: UploadReply.self)
            }
            update(ride.id) {
                $0.status = .uploaded
                $0.serverId = reply.serverId
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

    /// Rides to /rides, with the chosen bike; walks, runs and hikes to /workouts with their sport. The ride's id is the client_id
    /// there, so a retry after a dropped reply finds the first upload (as /rides does by content).
    nonisolated static func destination(_ ride: SavedRide) -> (path: String, fields: [String: String]) {
        let s = ride.summary
        if s.sport.isRide {
            return ("rides", s.bikeId.map { ["bike_id": String($0)] } ?? [:])
        }
        return ("workouts", ["sport": s.sport.rawValue, "name": ride.name, "client_id": ride.id.uuidString, "source": "ios"])
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
