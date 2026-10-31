import Foundation

/// A friend's share code: `hwfc_…`, or `headwind://friend?c=hwfc_…` as their QR code holds it (services/feed_tokens.py).
/// The app only recognises it; the server reads the address and token out of it.
enum FriendLink {
    static let codePrefix = "hwfc_"

    /// The code as typed, pasted or scanned, if it looks like one.
    static func code(in text: String) -> String? {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix(codePrefix), text.count > codePrefix.count + 16 {
            return text
        }
        guard let comps = URLComponents(string: text), comps.scheme?.lowercased() == "headwind", comps.host?.lowercased() == "friend",
              let code = comps.queryItems?.first(where: { $0.name == "c" })?.value, code.hasPrefix(codePrefix) else {
            return nil
        }
        return code
    }
}

/// Body of POST /api/v1/friends/tokens: what one friend may read, and the address their Headwind should use.
struct FriendTokenRequest: Encodable, Sendable {
    var name: String
    var rides: Bool
    var segments: Bool
    var foods: Bool
    /// "YYYY-MM-DD", or nil for no limit.
    var since: String?
    var until: String?
    var server_url: String
}

/// A new token for a friend, shown once: only its hash stays on the server.
struct FriendShare: Decodable, Sendable {
    let id: Int
    let token: String
    let url: String
    let code: String
    let link: String
}

/// Who a friend's code connects to (POST /api/v1/friends/probe).
struct FriendProbe: Decodable, Sendable {
    struct Rider: Decodable, Sendable, Hashable {
        let name: String
        let isDefault: Bool
    }
    let url: String
    let riders: [Rider]
}

struct FriendAddRequest: Encodable, Sendable {
    var code: String
    var rider: String
    var name: String
}
