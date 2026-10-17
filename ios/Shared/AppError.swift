import Foundation

/// Every error the app surfaces, on both iPhone and Watch. Throwing code uses typed throws (`throws(AppError)`)
/// so callers always know what they can get and every case has a message fit to show the user.
enum AppError: LocalizedError {
    /// The request never got an answer: offline, timeout, DNS, TLS.
    case networkError(underlying: Error)
    /// Input the app can't accept, with the reason to show.
    case validationError(message: String)
    /// No server paired yet.
    case notPaired
    /// The server rejected this phone's token (revoked on the Phones page).
    case unauthorised
    /// The server answered with an error status; `message` is its `{"error": …}` text when it sent one.
    case serverError(status: Int, message: String?)
    /// The reply wasn't the JSON Headwind sends (wrong address, or a login page / proxy in the way).
    case unexpectedResponse
    /// Reading or writing a file on this device failed.
    case storage(underlying: Error)
    /// HealthKit refused to start or save a workout.
    case health(underlying: Error)

    var errorDescription: String? {
        switch self {
        case .networkError(let error):
            return error.localizedDescription
        case .validationError(let message):
            return message
        case .notPaired:
            return "This phone isn't paired with a Headwind server yet."
        case .unauthorised:
            return "The server no longer accepts this phone's token. It may have been revoked on the Phones page. Pair again."
        case .serverError(let status, let message):
            return message ?? "The server answered with an error (HTTP \(status))."
        case .unexpectedResponse:
            return "The server's reply wasn't what Headwind sends. Check the address, and that nothing (a login page, a proxy) sits in front of /api/v1/."
        case .storage(let error):
            return "Couldn't save on this device: \(error.localizedDescription)"
        case .health(let error):
            return "Apple Health: \(error.localizedDescription)"
        }
    }

    var isNetworkError: Bool {
        if case .networkError = self { return true }
        return false
    }
}

// Validation messages used in more than one place (and checked by the tests).
extension AppError {
    static let notAPairingLink = AppError.validationError(
        message: "That isn't a Headwind pairing code. On your server, open Phones and create a new pairing.")
    static let missingServer = AppError.validationError(
        message: "Enter your Headwind address, e.g. https://bike.example.com.")
    static let insecureServer = AppError.validationError(
        message: "Headwind only pairs over https://. Use the address you reach it on through your reverse proxy.")
    static let badToken = AppError.validationError(
        message: "That token doesn't look right. Tokens start with hw_ and are shown once when you create a pairing.")
    static let rideTooShort = AppError.validationError(
        message: "Not enough GPS was recorded to save this ride. Wait for \"GPS ready\" before starting.")
}
