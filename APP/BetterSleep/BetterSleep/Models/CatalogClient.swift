import Foundation

actor CatalogClient {
    static let shared = CatalogClient()

    private let catalogURL = "http://127.0.0.1:8080"

    private var cachedUserServiceURL: String?
    private var cachedTimeSeriesURL: String?
    private var cacheTimestampUser: Date?
    private var cacheTimestampTS: Date?
    private let cacheTTL: TimeInterval = 60

    private func fixEndpoint(_ endpoint: String) -> String {
        endpoint.replacingOccurrences(of: "0.0.0.0", with: "127.0.0.1")
    }

    func getUserServiceURL() async throws -> String {
        if let cached = cachedUserServiceURL,
           let ts = cacheTimestampUser,
           Date().timeIntervalSince(ts) < cacheTTL {
            return cached
        }

        let url = URL(string: "\(catalogURL)/getEndpointUserService")!
        let (data, _) = try await URLSession.shared.data(from: url)

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let endpoint = json["endpoint"] as? String else {
            throw URLError(.badServerResponse)
        }

        let fixed = fixEndpoint(endpoint)
        cachedUserServiceURL = fixed
        cacheTimestampUser = Date()
        return fixed
    }

    func getTimeSeriesURL() async throws -> String {
        if let cached = cachedTimeSeriesURL,
           let ts = cacheTimestampTS,
           Date().timeIntervalSince(ts) < cacheTTL {
            return cached
        }

        let url = URL(string: "\(catalogURL)/getEndpointTimeSeries")!
        let (data, _) = try await URLSession.shared.data(from: url)

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let endpoint = json["endpoint"] as? String else {
            throw URLError(.badServerResponse)
        }

        let fixed = fixEndpoint(endpoint)
        cachedTimeSeriesURL = fixed
        cacheTimestampTS = Date()
        return fixed
    }

    /// Fetch active sensors for a room directly from the Catalog
    func getSensorsForRoom(roomID: String) async throws -> [Sensor] {
        let url = URL(string: "\(catalogURL)/getSensorByRoom?roomID=\(roomID)")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let sensorsData = try JSONSerialization.data(withJSONObject: json?["sensors"] ?? [])
        return try JSONDecoder().decode([Sensor].self, from: sensorsData)
    }

    /// Ask the user service to register default sensors for a room
    func activateSensors(roomId: Int, houseId: Int) async throws {
        let base = try await getUserServiceURL()
        var req = URLRequest(url: URL(string: "\(base)/activateSensors")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["room_id": roomId, "house_id": houseId])
        _ = try await URLSession.shared.data(for: req)
    }
}
