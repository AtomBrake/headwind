import SwiftUI
import UIKit

/// Photos for the server: iPhone pictures are HEIC, which the server can't read (services/photos.py PHOTO_EXTENSIONS), and full-size ones
/// waste mobile data, so each is redrawn as a JPEG no bigger than photos.FULL (1600 px) before it goes. Redrawing also leaves the original's
/// metadata (location and all) behind; the server strips EXIF as well.
enum PhotoPrep {
    static let maxSide: CGFloat = 1600

    static func jpeg(from data: Data, quality: CGFloat = 0.84) -> Data? {
        UIImage(data: data).flatMap { jpeg(from: $0, quality: quality) }
    }

    static func jpeg(from image: UIImage, quality: CGFloat = 0.84) -> Data? {
        let size = image.size
        let scale = min(1, maxSide / max(size.width, size.height, 1))
        let target = CGSize(width: (size.width * scale).rounded(), height: (size.height * scale).rounded())
        let format = UIGraphicsImageRendererFormat.default()
        format.scale = 1
        format.opaque = true
        let resized = UIGraphicsImageRenderer(size: target, format: format).image { _ in
            image.draw(in: CGRect(origin: .zero, size: target))     // draws upright, whatever the original's orientation
        }
        return resized.jpegData(compressionQuality: quality)
    }
}

/// A photo taken now with the camera (UIImagePickerController; the camera permission is NSCameraUsageDescription, shared with the QR scanner).
/// Calls `onImage` with the picture, or nothing when cancelled; either way the caller closes it.
struct CameraPicker: UIViewControllerRepresentable {
    var onImage: (UIImage?) -> Void

    static var isAvailable: Bool { UIImagePickerController.isSourceTypeAvailable(.camera) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onImage: onImage) }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onImage: (UIImage?) -> Void
        init(onImage: @escaping (UIImage?) -> Void) { self.onImage = onImage }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onImage(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onImage(nil) }
    }
}

/// An image the server serves only with the device token (GET /api/v1/photos/<name>), which AsyncImage can't send. Kept in memory for the
/// session so scrolling back doesn't fetch it again.
struct AuthedImage: View {
    /// The server's path for it, e.g. "/api/v1/photos/act_1a2b.jpg".
    var path: String
    var contentMode: ContentMode = .fill
    @Environment(Session.self) private var session
    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image).resizable().aspectRatio(contentMode: contentMode)
            } else if failed {
                Image(systemName: "photo").foregroundStyle(.secondary)
            } else {
                ProgressView()
            }
        }
        .task(id: path) { await load() }
    }

    private func load() async {
        if let cached = ImageCache.shared.object(forKey: path as NSString) {
            image = cached
            return
        }
        let relative = path.hasPrefix("/api/v1/") ? String(path.dropFirst("/api/v1/".count)) : path
        do throws(AppError) {
            let data = try await session.call { client async throws(AppError) in try await client.data(relative) }
            guard let loaded = UIImage(data: data) else { failed = true; return }
            ImageCache.shared.setObject(loaded, forKey: path as NSString)
            image = loaded
        } catch {
            failed = true
        }
    }
}

@MainActor
private enum ImageCache {
    static let shared: NSCache<NSString, UIImage> = {
        let cache = NSCache<NSString, UIImage>()
        cache.countLimit = 120
        return cache
    }()
}
