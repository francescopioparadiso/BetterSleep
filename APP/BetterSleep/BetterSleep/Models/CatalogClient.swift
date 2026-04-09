import Foundation

actor CatalogClient {
    static let shared = CatalogClient()

    private let defaultPublicHost = "127.0.0.1"
    private let loopbackHosts = ["0.0.0.0", "127.0.0.1", "localhost"]

    private var cachedUserServiceURL: String?
    private var cachedTimeSeriesURL: String?
    private var cacheTimestampUser: Date?
    private var cacheTimestampTS: Date?
    private let cacheTTL: TimeInterval = 60

    private func sanitizeHost(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !trimmed.hasPrefix("$(") else {
            return nil
        }
        return trimmed
    }

    private var publicHost: String {
        #if targetEnvironment(simulator)
        return defaultPublicHost
        #else
        let envHost = ProcessInfo.processInfo.environment["PUBLIC_HOST"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let envHost = sanitizeHost(envHost) {
            return envHost
        }

        let deviceHost = Bundle.main.object(forInfoDictionaryKey: "DEVICE_PUBLIC_HOST") as? String
        if let deviceHost = sanitizeHost(deviceHost) {
            return deviceHost
        }

        let plistHost = Bundle.main.object(forInfoDictionaryKey: "PUBLIC_HOST") as? String
        if let plistHost = sanitizeHost(plistHost) {
            return plistHost
        }

        return defaultPublicHost
        #endif
    }

    private var catalogURL: String {
        "http://\(publicHost):8080"
    }

    private func fixEndpoint(_ endpoint: String) -> String {
        guard var components = URLComponents(string: endpoint) else {
            return endpoint
        }

        if let host = components.host,
           shouldRewriteHost(host) {
            components.host = publicHost
        }

        return components.string ?? endpoint
    }

    private func shouldRewriteHost(_ host: String) -> Bool {
        let lowered = host.lowercased()
        if loopbackHosts.contains(lowered) {
            return true
        }

        // Docker service names like "user-service" are not resolvable from iOS.
        if !lowered.contains(".") {
            return true
        }

        // Private/local network addresses exposed by containers are not reachable from app clients.
        if lowered.hasPrefix("10.") || lowered.hasPrefix("172.") || lowered.hasPrefix("192.168.") {
            return true
        }

        return false
    }

    private func logPotentialDeviceMisconfiguration() {
        #if !targetEnvironment(simulator)
        if loopbackHosts.contains(publicHost.lowercased()) {
            print("CatalogClient warning: physical device is using loopback host '\(publicHost)'. Set DEVICE_PUBLIC_HOST in AppInfo.plist to your Mac LAN IP.")
        }
        #endif
    }

    func getUserServiceURL() async throws -> String {
        if let cached = cachedUserServiceURL,
           let ts = cacheTimestampUser,
           Date().timeIntervalSince(ts) < cacheTTL {
            return cached
        }

        let url = URL(string: "\(catalogURL)/getEndpointUserService")!
        logPotentialDeviceMisconfiguration()
        print("CatalogClient getUserServiceURL -> \(url.absoluteString)")
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
        logPotentialDeviceMisconfiguration()
        print("CatalogClient getTimeSeriesURL -> \(url.absoluteString)")
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
        let (data, response) = try await URLSession.shared.data(for: req)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let payload = String(data: data, encoding: .utf8) ?? ""
            throw NSError(
                domain: "CatalogClient",
                code: httpResponse.statusCode,
                userInfo: [NSLocalizedDescriptionKey: payload.isEmpty ? "Sensor activation failed" : payload]
            )
        }
    }
}
