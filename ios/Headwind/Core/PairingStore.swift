import Foundation
import Security

protocol PairingStore {
    func load() -> Pairing?
    func save(_ pairing: Pairing)
    func clear()
}

/// The token is a credential, so it lives in the Keychain rather than UserDefaults.
/// AfterFirstUnlock (not WhenUnlocked) so a future widget or background refresh can still read it.
struct KeychainPairingStore: PairingStore {
    var service = "io.github.atombrake.headwind.pairing"
    var account = "default"

    private var baseQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    func load() -> Pairing? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data else {
            return nil
        }
        return try? JSONDecoder().decode(Pairing.self, from: data)
    }

    func save(_ pairing: Pairing) {
        guard let data = try? JSONEncoder().encode(pairing) else { return }
        SecItemDelete(baseQuery as CFDictionary)
        var item = baseQuery
        item[kSecValueData as String] = data
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        SecItemAdd(item as CFDictionary, nil)
    }

    func clear() {
        SecItemDelete(baseQuery as CFDictionary)
    }
}

/// For previews and tests.
final class MemoryPairingStore: PairingStore {
    var pairing: Pairing?
    init(_ pairing: Pairing? = nil) { self.pairing = pairing }
    func load() -> Pairing? { pairing }
    func save(_ pairing: Pairing) { self.pairing = pairing }
    func clear() { pairing = nil }
}
