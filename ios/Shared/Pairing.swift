import Foundation

/// One paired server: its base address and the per-device token minted on the server's Phones page (see services/device_auth.py).
struct Pairing: Codable, Equatable, Sendable {
    var server: URL
    var token: String
}

/// Parses and validates `headwind://pair?u=<server>&t=<token>`, the link routes/phones.py puts in the QR code.
enum PairLink {
    static let tokenPrefix = "hw_"

    /// Plain http is only tolerated for a server on this machine, in debug builds, so the simulator can talk to a dev server.
    #if DEBUG
    static let allowsLocalHTTP = true
    #else
    static let allowsLocalHTTP = false
    #endif

    static func parse(_ text: String) throws(AppError) -> Pairing {
        guard let comps = URLComponents(string: text.trimmingCharacters(in: .whitespacesAndNewlines)),
              comps.scheme?.lowercased() == "headwind", comps.host?.lowercased() == "pair" else {
            throw .notAPairingLink
        }
        let items = comps.queryItems ?? []
        let server = items.first { $0.name == "u" }?.value ?? ""
        let token = items.first { $0.name == "t" }?.value ?? ""
        return try make(server: server, token: token)
    }

    static func make(server: String, token: String) throws(AppError) -> Pairing {
        var address = server.trimmingCharacters(in: .whitespacesAndNewlines)
        while address.hasSuffix("/") { address.removeLast() }
        guard let url = URL(string: address), let scheme = url.scheme?.lowercased(),
              let host = url.host(), !host.isEmpty else {
            throw .missingServer
        }
        let isLocal = ["localhost", "127.0.0.1", "::1"].contains(host.lowercased())
        guard scheme == "https" || (scheme == "http" && isLocal && allowsLocalHTTP) else {
            throw .insecureServer
        }
        let t = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.hasPrefix(tokenPrefix), t.count > tokenPrefix.count + 16 else {
            throw .badToken
        }
        return Pairing(server: url, token: t)
    }
}
