import Foundation

actor CatalogClient {
    static let shared = CatalogClient()

    private let catalogURL = "http://127.0.0.1:8080"

    private var cachedUserServiceURL: String?
    private var cacheTimestamp: Date?
    private let cacheTTL: TimeInterval = 60

    func getUserServiceURL() async throws -> String {
        if let cached = cachedUserServiceURL,
           let ts = cacheTimestamp,
           Date().timeIntervalSince(ts) < cacheTTL {
            return cached
        }

        let url = URL(string: "\(catalogURL)/getEndpointUserService")!
        let (data, _) = try await URLSession.shared.data(from: url)

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              var endpoint = json["endpoint"] as? String else {
            throw URLError(.badServerResponse)
        }

        // Replace 0.0.0.0 so iOS can reach the service
        endpoint = endpoint.replacingOccurrences(of: "0.0.0.0", with: "127.0.0.1")

        cachedUserServiceURL = endpoint
        cacheTimestamp = Date()
        return endpoint
    }
}
