import Foundation
import SwiftUI
import Combine

@MainActor
class HouseModel: ObservableObject {
    @Published var houses: [House] = []
    @Published var pendingInvites: [Invitation] = []
    @Published var isLoading = true
    
    @Published var currentUserId: Int?
    @Published var currentHouseMembers: [HouseMember] = []
    @Published var currentHouseInvites: [Invitation] = []
    
    // Change this to match your actual Python service IP/Port
    private let baseURL = "http://127.0.0.1:9095"
    
    init() {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            self.currentUserId = id
        }
    }
    
    // MARK: - API Helpers
    private func fetchFromAPI<T: Decodable>(endpoint: String, responseKey: String) async throws -> T {
        let url = URL(string: "\(baseURL)/\(endpoint)")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let itemData = try JSONSerialization.data(withJSONObject: json?[responseKey] ?? [])
        return try JSONDecoder().decode(T.self, from: itemData)
    }
    
    // MARK: - House Actions
    func fetchHouses() async {
        isLoading = true
        guard let userId = currentUserId else { return }
        do {
            let allMembers: [HouseMember] = try await fetchFromAPI(endpoint: "getAllHouseMembers", responseKey: "house_members")
            let myHouseIds = allMembers.filter { $0.user_id == userId }.map { $0.house_id }
            
            let allHouses: [House] = try await fetchFromAPI(endpoint: "getAllHouses", responseKey: "houses")
            self.houses = allHouses.filter { myHouseIds.contains($0.id ?? -1) }
        } catch {
            print("Error fetching houses: \(error)")
        }
        isLoading = false
    }
    
    func addHouse(name: String) async {
        guard let userId = currentUserId else { return }
        do {
            var req = URLRequest(url: URL(string: "\(baseURL)/addHouse")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["name": name])
            
            let (data, _) = try await URLSession.shared.data(for: req)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let newHouseId = json["id"] as? Int {
                
                // Add the user as Owner (role 0)
                var memberReq = URLRequest(url: URL(string: "\(baseURL)/addHouseMember")!)
                memberReq.httpMethod = "POST"
                memberReq.setValue("application/json", forHTTPHeaderField: "Content-Type")
                memberReq.httpBody = try JSONSerialization.data(withJSONObject: ["house_id": newHouseId, "user_id": userId, "role": 0])
                _ = try await URLSession.shared.data(for: memberReq)
                
                await fetchHouses()
            }
        } catch { print("Error creating house: \(error)") }
    }
    
    func deleteHouse(at offsets: IndexSet) async {
        for index in offsets {
            guard let houseId = houses[index].id else { continue }
            do {
                var req = URLRequest(url: URL(string: "\(baseURL)/removeHouse?id=\(houseId)")!)
                req.httpMethod = "DELETE"
                _ = try await URLSession.shared.data(for: req)
                self.houses.remove(at: index)
            } catch { print("Error deleting house: \(error)") }
        }
    }
    
    // MARK: - Invitation Actions
    func fetchPendingInvites() async {
        guard let userId = currentUserId else { return }
        do {
            let allUsers: [User] = try await fetchFromAPI(endpoint: "getAllUsers", responseKey: "users")
            guard let myEmail = allUsers.first(where: { $0.id == userId })?.email else { return }
            
            let allInvites: [Invitation] = try await fetchFromAPI(endpoint: "getAllInvitations", responseKey: "invitations")
            self.pendingInvites = allInvites.filter { $0.email.lowercased() == myEmail.lowercased() && $0.status == 0 }
        } catch { print("Error fetching invites: \(error)") }
    }
    
    func inviteUser(email: String, to houseId: Int) async {
        do {
            var req = URLRequest(url: URL(string: "\(baseURL)/addInvitation")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["house_id": houseId, "email": email, "status": 0])
            _ = try await URLSession.shared.data(for: req)
        } catch { print("Error sending invite: \(error)") }
    }
    
    func acceptInvite(invite: Invitation) async {
        guard let userId = currentUserId, let inviteId = invite.id else { return }
        do {
            var joinReq = URLRequest(url: URL(string: "\(baseURL)/addHouseMember")!)
            joinReq.httpMethod = "POST"
            joinReq.setValue("application/json", forHTTPHeaderField: "Content-Type")
            joinReq.httpBody = try JSONSerialization.data(withJSONObject: ["house_id": invite.house_id, "user_id": userId, "role": 1])
            _ = try await URLSession.shared.data(for: joinReq)
            
            var updateReq = URLRequest(url: URL(string: "\(baseURL)/updateInvitation")!)
            updateReq.httpMethod = "PUT"
            updateReq.setValue("application/json", forHTTPHeaderField: "Content-Type")
            updateReq.httpBody = try JSONSerialization.data(withJSONObject: ["id": inviteId, "house_id": invite.house_id, "email": invite.email, "status": 1])
            _ = try await URLSession.shared.data(for: updateReq)
            
            await fetchHouses()
            await fetchPendingInvites()
        } catch { print("Error accepting: \(error)") }
    }
    
    func rejectInvite(invite: Invitation) async {
        guard let inviteId = invite.id else { return }
        do {
            var req = URLRequest(url: URL(string: "\(baseURL)/updateInvitation")!)
            req.httpMethod = "PUT"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["id": inviteId, "house_id": invite.house_id, "email": invite.email, "status": 2]) // 2 = rejected
            _ = try await URLSession.shared.data(for: req)
            await fetchPendingInvites()
        } catch { print("Error rejecting: \(error)") }
    }
    
    // MARK: - Manage Invites & Members
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
    
    func checkUserExists(email: String) async -> Bool {
        do {
            let allUsers: [User] = try await fetchFromAPI(endpoint: "getAllUsers", responseKey: "users")
            return allUsers.contains { $0.email.lowercased() == email.lowercased() }
        } catch { return false }
    }
    
    func removeMember(memberId: Int) async {
        do {
            var req = URLRequest(url: URL(string: "\(baseURL)/removeHouseMember?id=\(memberId)")!)
            req.httpMethod = "DELETE"
            _ = try await URLSession.shared.data(for: req)
            self.currentHouseMembers.removeAll { $0.id == memberId }
        } catch { print("Error removing member: \(error)") }
    }
}
