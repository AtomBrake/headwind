import Foundation

/// The phone API (routes/api_v1.py): requests with a Bearer device token, JSON back.
struct APIClient: Sendable {
    let pairing: Pairing
    var urlSession: URLSession = .shared

    func get<T: Decodable & Sendable>(_ path: String, as type: T.Type = T.self) async throws(AppError) -> T {
        try await send(request(path), as: type)
    }

    /// POST a JSON body (e.g. /live).
    func post<T: Decodable & Sendable>(_ path: String, json body: some Encodable, as type: T.Type = T.self) async throws(AppError) -> T {
        var req = request(path, method: "POST")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            req.httpBody = try JSONEncoder().encode(body)
        } catch {
            throw .validationError(message: "Couldn't encode the request: \(error.localizedDescription)")
        }
        return try await send(req, as: type)
    }

    /// POST one file as multipart/form-data field `file` (e.g. a GPX to /rides), plus any plain form `fields`.
    func upload<T: Decodable & Sendable>(_ path: String, file: Data, filename: String, mimeType: String, fields: [String: String] = [:],
                                         as type: T.Type = T.self) async throws(AppError) -> T {
        let boundary = "headwind-\(UUID().uuidString)"
        var body = Data()
        for (name, value) in fields.sorted(by: { $0.key < $1.key }) {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".utf8))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(file)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        var req = request(path, method: "POST")
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        req.timeoutInterval = 120   // the server matches segments and fetches weather before it answers
        return try await send(req, as: type)
    }

    private func request(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: pairing.server.appending(path: "api/v1/\(path)"))
        request.httpMethod = method
        request.setValue("Bearer \(pairing.token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 20
        return request
    }

    private func send<T: Decodable & Sendable>(_ request: URLRequest, as type: T.Type) async throws(AppError) -> T {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await urlSession.data(for: request)
        } catch {
            throw .networkError(underlying: error)
        }
        guard let http = response as? HTTPURLResponse else { throw .unexpectedResponse }
        switch http.statusCode {
        case 200..<300:
            break
        case 401:
            throw .unauthorised
        default:
            throw .serverError(status: http.statusCode, message: try? JSONDecoder().decode(ServerError.self, from: data).error)
        }
        do {
            return try JSONDecoder.headwind.decode(T.self, from: data)
        } catch {
            throw .unexpectedResponse
        }
    }
}

private struct ServerError: Decodable {
    let error: String
}

extension JSONDecoder {
    /// The API mixes snake_case envelope keys (water_ml) with camelCase row keys (foodName); this maps both onto Swift names.
    static var headwind: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
