import Foundation
import SwiftUI
import Combine

@MainActor
class HouseModel: ObservableObject {
    @Published var houses: [House] = []
    @Published var pendingInvites: [Invitation] = []
    @Published var pendingInviteHouseNames: [Int: String] = [:]
    @Published var isLoading = true
    @Published var currentUserId: Int?
    
    private func baseURL() async throws -> String {
        try await CatalogClient.shared.getUserServiceURL()
    }
    
    init() {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            self.currentUserId = id
        }
    }
    
    // MARK: - API Helpers
    private func fetchFromAPI<T: Decodable>(endpoint: String, responseKey: String) async throws -> T {
        let base = try await baseURL()
        let url = URL(string: "\(base)/\(endpoint)")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let itemData = try JSONSerialization.data(withJSONObject: json?[responseKey] ?? [])
        return try JSONDecoder().decode(T.self, from: itemData)
    }
    
    // MARK: - House Actions
    func fetchHouses() async {
        isLoading = true
        defer { isLoading = false }
        guard let userId = currentUserId else { return }
        do {
            let allMembers: [HouseMember] = try await fetchFromAPI(endpoint: "getAllHouseMembers", responseKey: "house_members")
            let myHouseIds = allMembers.filter { $0.user_id == userId }.map { $0.house_id }
            
            let allHouses: [House] = try await fetchFromAPI(endpoint: "getAllHouses", responseKey: "houses")
            self.houses = allHouses.filter { myHouseIds.contains($0.id ?? -1) }
        } catch {
            print("Error fetching houses: \(error)")
        }
    }
    
    func addHouse(name: String) async {
        guard let userId = currentUserId else { return }
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/addHouse")!)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["name": name])
            
            let (data, _) = try await URLSession.shared.data(for: req)
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let newHouseId = json["id"] as? Int {
                
                var memberReq = URLRequest(url: URL(string: "\(base)/addHouseMember")!)
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
                let base = try await baseURL()
                var req = URLRequest(url: URL(string: "\(base)/removeHouse?id=\(houseId)")!)
                req.httpMethod = "DELETE"
                _ = try await URLSession.shared.data(for: req)
                self.houses.remove(at: index)
            } catch { print("Error deleting house: \(error)") }
        }
    }
    
    // MARK: - Pending Invites (for HousesView)
    func fetchPendingInvites() async {
        guard let userId = currentUserId else { return }
        do {
            let allUsers: [User] = try await fetchFromAPI(endpoint: "getAllUsers", responseKey: "users")
            guard let myEmail = allUsers.first(where: { $0.id == userId })?.email else { return }
            
            let allInvites: [Invitation] = try await fetchFromAPI(endpoint: "getAllInvitations", responseKey: "invitations")
            let myPendingInvites = allInvites.filter { $0.email.lowercased() == myEmail.lowercased() && $0.status == 0 }
            self.pendingInvites = myPendingInvites

            let allHouses: [House] = try await fetchFromAPI(endpoint: "getAllHouses", responseKey: "houses")
            var names: [Int: String] = [:]
            for invite in myPendingInvites {
                if let houseName = allHouses.first(where: { $0.id == invite.house_id })?.name {
                    names[invite.house_id] = houseName
                }
            }
            self.pendingInviteHouseNames = names
        } catch { print("Error fetching invites: \(error)") }
    }
    
    func acceptInvite(invite: Invitation) async {
        guard let userId = currentUserId, let inviteId = invite.id else { return }
        do {
            let base = try await baseURL()
            var joinReq = URLRequest(url: URL(string: "\(base)/addHouseMember")!)
            joinReq.httpMethod = "POST"
            joinReq.setValue("application/json", forHTTPHeaderField: "Content-Type")
            joinReq.httpBody = try JSONSerialization.data(withJSONObject: ["house_id": invite.house_id, "user_id": userId, "role": 1])
            _ = try await URLSession.shared.data(for: joinReq)
            
            var updateReq = URLRequest(url: URL(string: "\(base)/updateInvitation")!)
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
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/updateInvitation")!)
            req.httpMethod = "PUT"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: ["id": inviteId, "house_id": invite.house_id, "email": invite.email, "status": 2])
            _ = try await URLSession.shared.data(for: req)
            await fetchPendingInvites()
        } catch { print("Error rejecting: \(error)") }
    }
}
