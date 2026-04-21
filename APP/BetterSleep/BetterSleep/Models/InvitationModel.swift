import Foundation
import SwiftUI
import Combine

@MainActor
class InvitationModel: ObservableObject {
    @Published var currentHouseMembers: [HouseMember] = []
    @Published var currentHouseInvites: [Invitation] = []
    @Published var errorMessage: String? = nil
    
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
    
    func fetchHouseDetails(for houseId: Int) async {
        do {
            let allMembers: [HouseMember] = try await fetchFromAPI(endpoint: "getAllHouseMembers", responseKey: "house_members")
            let allUsers: [User] = try await fetchFromAPI(endpoint: "getAllUsers", responseKey: "users")
            
            var membersInHouse = allMembers.filter { $0.house_id == houseId }
            for i in 0..<membersInHouse.count {
                if let user = allUsers.first(where: { $0.id == membersInHouse[i].user_id }) {
                    membersInHouse[i].email = user.email
                }
            }
            self.currentHouseMembers = membersInHouse
            
            let allInvites: [Invitation] = try await fetchFromAPI(endpoint: "getAllInvitations", responseKey: "invitations")
            self.currentHouseInvites = allInvites.filter { $0.house_id == houseId }
        } catch { print("Error fetching details: \(error)") }
    }
    
    func inviteUser(email: String, to houseId: Int) async {
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/addInvitation")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["house_id": houseId, "email": email, "status": 0])
            
            let (data, response) = try await URLSession.shared.data(for: req)
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode != 200 && httpResponse.statusCode != 201 {
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    if let message = json["error"] as? String {
                        self.errorMessage = message
                    } else if let message = json["message"] as? String {
                        self.errorMessage = message
                    } else {
                        self.errorMessage = "Failed to send invitation."
                    }
                } else {
                    self.errorMessage = "Failed to send invitation."
                }
            } else {
                self.errorMessage = nil
            }
        } catch { 
            print("Error sending invite: \(error)")
            self.errorMessage = "Network error occurred."
        }
    }
    
    func checkUserExists(email: String) async -> Bool {
        do {
            let allUsers: [User] = try await fetchFromAPI(endpoint: "getAllUsers", responseKey: "users")
            return allUsers.contains { $0.email.lowercased() == email.lowercased() }
        } catch { return false }
    }
    
    func removeMember(memberId: Int) async {
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/removeHouseMember?id=\(memberId)")!)
            req.httpMethod = "DELETE"
            _ = try await URLSession.shared.data(for: req)
            self.currentHouseMembers.removeAll { $0.id == memberId }
        } catch { print("Error removing member: \(error)") }
    }
    
    func deleteInvite(inviteId: Int) async {
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/removeInvitation?id=\(inviteId)")!)
            req.httpMethod = "DELETE"
            _ = try await URLSession.shared.data(for: req)
        } catch { print("Error deleting invite: \(error)") }
    }
}
