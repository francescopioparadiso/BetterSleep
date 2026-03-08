import Foundation
import SwiftUI
import Combine

@MainActor
class RoomModel: ObservableObject {
    @Published var rooms: [Room] = []
    
    private var currentUserId: Int? {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            return id
        }
        return nil
    }
    
    private func baseURL() async throws -> String {
        try await CatalogClient.shared.getUserServiceURL()
    }
    
    private func fetchFromAPI<T: Decodable>(endpoint: String, responseKey: String) async throws -> T {
        let base = try await baseURL()
        let url = URL(string: "\(base)/\(endpoint)")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let itemData = try JSONSerialization.data(withJSONObject: json?[responseKey] ?? [])
        return try JSONDecoder().decode(T.self, from: itemData)
    }
    
    func fetchRooms(for houseId: Int) async {
        do {
            let allRooms: [Room] = try await fetchFromAPI(endpoint: "getAllRooms", responseKey: "rooms")
            self.rooms = allRooms.filter { $0.house_id == houseId }
        } catch { print("Error fetching rooms: \(error)") }
    }
    
    func addRoom(name: String, houseId: Int) async {
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/addRoom")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["house_id": houseId, "name": name])
            _ = try await URLSession.shared.data(for: req)
            await fetchRooms(for: houseId)
        } catch { print("Error adding room: \(error)") }
    }
    
    func deleteRoom(roomId: Int, houseId: Int) async {
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/removeRoom?id=\(roomId)")!)
            req.httpMethod = "DELETE"
            _ = try await URLSession.shared.data(for: req)
            self.rooms.removeAll { $0.id == roomId }
        } catch { print("Error deleting room: \(error)") }
    }

    private var updateTask: Task<Void, Never>?

    func updateRoomDebounced(_ room: Room) {
        updateTask?.cancel()
        updateTask = Task {
            do {
                try await Task.sleep(nanoseconds: 800_000_000)
                let base = try await baseURL()
                var req = URLRequest(url: URL(string: "\(base)/updateRoom")!)
                req.httpMethod = "PUT"
                req.setValue("application/json", forHTTPHeaderField: "Content-Type")
                let body: [String: Any] = [
                    "id": room.id ?? 0,
                    "temperature_night": room.temperature_night ?? 18,
                    "temperature_morning": room.temperature_morning ?? 22,
                    "light_night": room.light_night ?? 0,
                    "light_morning": room.light_morning ?? 100
                ]
                req.httpBody = try JSONSerialization.data(withJSONObject: body)
                _ = try await URLSession.shared.data(for: req)
            } catch is CancellationError {
                // Expected
            } catch {
                print("Error updating room: \(error)")
            }
        }
    }

    func assignRoom(roomId: Int, houseId: Int) async {
        guard let userId = currentUserId else { return }
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/assignRoom")!)
            req.httpMethod = "PUT"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: [
                "room_id": roomId, "user_id": userId, "house_id": houseId
            ])
            _ = try await URLSession.shared.data(for: req)
            await fetchRooms(for: houseId)
        } catch { print("Error assigning room: \(error)") }
    }

    func unassignRoom(roomId: Int, houseId: Int) async {
        guard let userId = currentUserId else { return }
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/unassignRoom")!)
            req.httpMethod = "PUT"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: [
                "room_id": roomId, "user_id": userId
            ])
            _ = try await URLSession.shared.data(for: req)
            await fetchRooms(for: houseId)
        } catch { print("Error unassigning room: \(error)") }
    }

    func setActiveRoom(roomId: Int, houseId: Int) async {
        guard let userId = currentUserId else { return }
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/setActiveRoom")!)
            req.httpMethod = "PUT"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: [
                "room_id": roomId, "user_id": userId
            ])
            _ = try await URLSession.shared.data(for: req)
            await fetchRooms(for: houseId)
        } catch { print("Error setting active room: \(error)") }
    }

    func deactivateRoom(roomId: Int, houseId: Int) async {
        guard let userId = currentUserId else { return }
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/setActiveRoom")!)
            req.httpMethod = "PUT"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            // Send empty/null to deactivate - backend will set active to false
            req.httpBody = try JSONSerialization.data(withJSONObject: [
                "room_id": roomId, "user_id": userId, "active": false
            ])
            _ = try await URLSession.shared.data(for: req)
            await fetchRooms(for: houseId)
        } catch { print("Error deactivating room: \(error)") }
    }

    func fetchActiveRoom(for userId: Int) async {
        do {
            let base = try await baseURL()
            let url = URL(string: "\(base)/getActiveRoom?user_id=\(userId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            
            if let activeRoomData = json?["active_room"] as? [String: Any],
               let activeRoomId = activeRoomData["id"] as? Int {
                // Mark the active room
                if let index = self.rooms.firstIndex(where: { $0.id == activeRoomId }) {
                    self.rooms[index].active = true
                }
            } else {
                // No active room - deactivate all
                for i in self.rooms.indices {
                    self.rooms[i].active = false
                }
            }
        } catch { print("Error fetching active room: \(error)") }
    }
}
