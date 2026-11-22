import Foundation
import UserNotifications

/// The notification for a live tracking link the Watch started: the Watch has no share sheet, so the phone says the link is ready, and a
/// tap opens the app with the link in the share sheet. Shown with the app open too. Without permission the link still waits on the
/// Record screen.
@MainActor
final class LiveLinkNotifier: NSObject, UNUserNotificationCenterDelegate {
    /// A notification was tapped: the recording whose link to offer.
    var onOpen: ((String) -> Void)?
    nonisolated private static let recordingKey = "live-recording"

    override init() {
        super.init()
        UNUserNotificationCenter.current().delegate = self      // at launch, so a tap that launched the app is heard
    }

    /// Asked when sharing is switched on in Settings (the Watch's switch starts from it), and when a link from the Watch arrives with the
    /// app open. iOS asks the person once.
    func askPermission() {
        Task { _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) }
    }

    func announce(_ link: LiveShareController.Link) {
        let content = UNMutableNotificationContent()
        let what = link.sport.map { Sport(stored: $0).title.lowercased() } ?? "recording"
        content.title = "Your live link is ready"
        content.body = "Your Watch started a link for your \(what). Tap to send it. Anyone with the link can see where you are."
        content.sound = .default
        content.userInfo = [Self.recordingKey: link.recording]
        let request = UNNotificationRequest(identifier: "live-link-\(link.recording)", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }

    /// The recording's link has ended (or been stopped): its notification is no use any more.
    func withdraw(recording: String) {
        UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: ["live-link-\(recording)"])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse) async {
        guard let recording = response.notification.request.content.userInfo[Self.recordingKey] as? String else { return }
        await MainActor.run { onOpen?(recording) }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                            willPresent notification: UNNotification) async -> UNNotificationPresentationOptions {
        [.banner, .list, .sound]
    }
}
