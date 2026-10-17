import Foundation
import Observation
import UIKit

/// A finished ride kept on the phone: its GPX, headline numbers, where it came from and whether it reached the server.
struct SavedRide: Codable, Identifiable, Equatable {
    enum Source: String, Codable { case phone, watch }
    enum Status: String, Codable { case pending, uploading, uploaded, failed }

    var id: UUID
    var summary: RideSummary
    var source: Source
    var status: Status
    /// Why the last upload failed, or the server's note (e.g. "Already on the server").
    var message: String?
    /// Activity id on the server once uploaded.
    var serverId: String?

    var filename: String { "\(id.uuidString).gpx" }
}

/// POST /api/v1/rides reply (routes/api_v1.py upload_ride).
private struct UploadReply: Decodable, Sendable {
    var status: String
    var ride: Ride?
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

    init(directory: URL? = nil) {
        let base = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        self.directory = directory ?? base.appending(path: "Recordings", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: self.directory, withIntermediateDirectories: true)
        load()
    }

    var pendingCount: Int { rides.filter { $0.status != .uploaded }.count }

    @discardableResult
    func add(gpx: Data, summary: RideSummary, source: SavedRide.Source) throws(AppError) -> SavedRide {
        let ride = SavedRide(id: UUID(), summary: summary, source: source, status: .pending)
        do {
            try gpx.write(to: fileURL(ride), options: .atomic)
        } catch {
            throw .storage(underlying: error)
        }
        insert(ride)
        return ride
    }

    /// Takes ownership of a GPX file (moved, not copied), e.g. one that arrived from the Watch.
    @discardableResult
    func adopt(file: URL, summary: RideSummary, source: SavedRide.Source) throws(AppError) -> SavedRide {
        let ride = SavedRide(id: UUID(), summary: summary, source: source, status: .pending)
        do {
            try FileManager.default.moveItem(at: file, to: fileURL(ride))
        } catch {
            throw .storage(underlying: error)
        }
        insert(ride)
        return ride
    }

    private func insert(_ ride: SavedRide) {
        rides.insert(ride, at: 0)
        rides.sort { $0.summary.start > $1.summary.start }
        save()
    }

    func delete(_ ride: SavedRide) {
        try? FileManager.default.removeItem(at: fileURL(ride))
        rides.removeAll { $0.id == ride.id }
        save()
    }

    func gpxURL(for ride: SavedRide) -> URL { fileURL(ride) }

    /// Upload everything not yet on the server, oldest first. Safe to call often; overlapping calls are ignored.
    func uploadPending(using session: Session) async {
        guard !uploading, session.pairing != nil else { return }
        uploading = true
        defer { uploading = false }

        // Finish even if the user locks the phone straight after stopping a ride.
        let task = UIApplication.shared.beginBackgroundTask(withName: "Upload rides")
        defer { if task != .invalid { UIApplication.shared.endBackgroundTask(task) } }

        for ride in rides.reversed() where ride.status != .uploaded {
            guard let data = try? Data(contentsOf: fileURL(ride)) else {
                update(ride.id) { $0.status = .failed; $0.message = "The recording file is missing." }
                continue
            }
            update(ride.id) { $0.status = .uploading; $0.message = nil }
            do throws(AppError) {
                let filename = "\(GPXWriter.rideName(start: ride.summary.start)).gpx"
                let reply = try await session.call { client async throws(AppError) in
                    try await client.upload("rides", file: data, filename: filename, mimeType: "application/gpx+xml", as: UploadReply.self)
                }
                update(ride.id) {
                    $0.status = .uploaded
                    $0.serverId = reply.ride?.id
                    $0.message = reply.status == "imported" ? nil : "Already on the server"
                }
            } catch {
                update(ride.id) { $0.status = .failed; $0.message = error.localizedDescription }
                if error.isNetworkError { break }   // offline: don't burn through the rest
            }
        }
    }

    private func update(_ id: UUID, _ change: (inout SavedRide) -> Void) {
        guard let i = rides.firstIndex(where: { $0.id == id }) else { return }
        change(&rides[i])
        save()
    }

    private func fileURL(_ ride: SavedRide) -> URL { directory.appending(path: ride.filename) }
    private var indexURL: URL { directory.appending(path: "index.json") }

    private func load() {
        guard let data = try? Data(contentsOf: indexURL),
              let saved = try? JSONDecoder().decode([SavedRide].self, from: data) else { return }
        // An upload interrupted by the app being killed is just pending again.
        rides = saved.map { var r = $0; if r.status == .uploading { r.status = .pending }; return r }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(rides) {
            try? data.write(to: indexURL, options: .atomic)
        }
    }
}
