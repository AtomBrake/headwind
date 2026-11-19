import Foundation
import Observation

/// App-wide state: which server this phone is paired with, and what that server told us about itself.
@MainActor
@Observable
final class Session {
    private(set) var pairing: Pairing?
    private(set) var info: PingInfo?
    /// Set when the server rejects the token, so the pairing screen can say why the user is back there.
    var wasRevoked = false
    /// A pairing link opened (e.g. from the Camera app) while already paired; waits for the user to confirm the switch.
    var pendingLink: String?
    /// A friend's code opened as a headwind://friend link; MainTabs offers to add them (once paired, if this phone isn't yet).
    var pendingFriendCode: String?
    /// The server this phone was last paired with, kept through unpair(): a ride finished after the phone was unpaired mid-ride still
    /// belongs to the server it was recorded under (RideStore.serverForNewRides).
    private(set) var lastServer: URL?
    /// A new address the server gave that the user said "Not now" to, so it isn't offered again.
    private var declinedMove: String?

    private let store: PairingStore
    private let defaults: UserDefaults
    private static let infoKey = "ping-info"
    private static let lastServerKey = "last-server"
    private static let declinedMoveKey = "declined-server-move"

    init(store: PairingStore = KeychainPairingStore(), defaults: UserDefaults = .standard) {
        self.store = store
        self.defaults = defaults
        pairing = store.load()
        lastServer = pairing?.server ?? defaults.url(forKey: Self.lastServerKey)
        if let lastServer { defaults.set(lastServer, forKey: Self.lastServerKey) }   // paired before this was kept
        declinedMove = defaults.string(forKey: Self.declinedMoveKey)
        if pairing != nil, let data = defaults.data(forKey: Self.infoKey) {
            info = try? JSONDecoder().decode(PingInfo.self, from: data)
        }
    }

    var units: Units { Units(system: info?.units) }
    var bikes: [Bike] { info?.bikes ?? [] }

    /// Validates the link, checks the server accepts the token, and only then stores it.
    func pair(link: String) async throws(AppError) {
        try await pair(with: PairLink.parse(link))
    }

    func pair(with candidate: Pairing) async throws(AppError) {
        let ping = try await APIClient(pairing: candidate).get("ping", as: PingInfo.self)
        store.save(candidate)
        pairing = candidate
        lastServer = candidate.server
        defaults.set(candidate.server, forKey: Self.lastServerKey)
        remember(ping)
        wasRevoked = false
        pendingLink = nil
    }

    /// The server's outside address (PingInfo.serverUrl) when it isn't the address this phone paired with: it moved, or the phone paired over
    /// the home network. nil once the user has said no to that address, and for one the app couldn't pair with (not https).
    var movedServer: URL? {
        guard let pairing, let text = info?.serverUrl, text != declinedMove,
              let url = try? PairLink.make(server: text, token: pairing.token).server, !url.isSameServer(as: pairing.server) else { return nil }
        return url
    }

    /// Pair with the same server at its new address, with the same token. Session.pair stores it only once the new address answers /ping
    /// with that token, so an address that doesn't work from here leaves the pairing as it is.
    func move(to server: URL) async throws(AppError) {
        guard let pairing else { throw .notPaired }
        try await pair(with: Pairing(server: server, token: pairing.token))
    }

    func declineMove() {
        guard let text = info?.serverUrl else { return }
        declinedMove = text
        defaults.set(text, forKey: Self.declinedMoveKey)
    }

    func unpair() {
        store.clear()
        defaults.removeObject(forKey: Self.infoKey)
        pairing = nil
        info = nil
    }

    /// Opened via the headwind:// URL scheme. A pairing link waits for the user to confirm its server, since any web page or message can
    /// open one: PairingView asks when unpaired, RootView when it would replace the current server. A friend's code goes to MainTabs instead.
    func handle(url: URL) {
        if let code = FriendLink.code(in: url.absoluteString) {
            pendingFriendCode = code
        } else {
            pendingLink = url.absoluteString
        }
    }

    /// Every screen loads through here so a revoked token sends the user back to pairing, wherever it's noticed.
    func load<T: Decodable & Sendable>(_ path: String, query: [URLQueryItem] = [], as type: T.Type = T.self) async throws(AppError) -> T {
        try await call { client async throws(AppError) in try await client.get(path, query: query, as: type) }
    }

    func call<T: Sendable>(_ request: (APIClient) async throws(AppError) -> T) async throws(AppError) -> T {
        guard let pairing else { throw .notPaired }
        do {
            return try await request(APIClient(pairing: pairing))
        } catch .unauthorised {
            unpair()
            wasRevoked = true
            throw .unauthorised
        }
    }

    func refreshInfo() async {
        if let ping = try? await load("ping", as: PingInfo.self) {
            remember(ping)
        }
    }

    private func remember(_ ping: PingInfo) {
        info = ping
        if let data = try? JSONEncoder().encode(ping) {
            defaults.set(data, forKey: Self.infoKey)
        }
    }
}
