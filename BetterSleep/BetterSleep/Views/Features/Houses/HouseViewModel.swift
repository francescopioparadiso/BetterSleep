import Foundation
import SwiftUI
import Combine
import Supabase

@MainActor
class HouseViewModel: ObservableObject {
    @Published var houses: [House] = []
    @Published var pendingInvites: [Invitation] = []
    @Published var isLoading = true
    
    @Published var currentUserId: UUID?
    @Published var currentHouseMembers: [HouseMember] = []
    @Published var currentHouseInvites: [Invitation] = []
    
    // MARK: - House Actions
    func fetchHouses() async {
        isLoading = true
        do {
            self.houses = try await supabase
                .from("houses")
                .select()
                .order("created_at", ascending: true)
                .execute()
                .value
            
            print("✅ Successfully fetched \(self.houses.count) houses!")
        } catch {
            // This will print the exact reason if it ever fails again
            print("❌ ERROR FETCHING HOUSES: \(error.localizedDescription)")
            print("Detailed error: \(error)")
        }
        isLoading = false
    }
    
    func addHouse(name: String) async {
        do {
            let session = try await supabase.auth.session
            let userId = session.user.id
            
            // 1. Generate the unique ID locally in Swift!
            let newHouseId = UUID()
            let newHouse = House(id: newHouseId, name: name)
            
            // 2. Insert the house (Notice we removed .select() and .single()!)
            try await supabase
                .from("houses")
                .insert(newHouse)
                .execute()
            
            // 3. Link the user to the house using our locally generated ID
            let memberData = [
                "house_id": newHouseId.uuidString,
                "user_id": userId.uuidString,
                "role": "owner"
            ]
            
            try await supabase
                .from("house_members")
                .insert(memberData)
                .execute()
            
            // 4. Update the UI
            self.houses.append(newHouse)
            
        } catch {
            print("Error creating house: \(error)")
        }
    }
    
    func deleteHouse(at offsets: IndexSet) async {
        for index in offsets {
            let houseToDelete = houses[index]
            guard let houseId = houseToDelete.id else { continue }
            
            do {
                try await supabase
                    .from("houses")
                    .delete()
                    .eq("id", value: houseId)
                    .execute()
                
                // If the database delete is successful, remove it from the UI
                self.houses.remove(at: index)
                print("✅ House '\(houseToDelete.name)' deleted successfully!")
                
            } catch {
                print("❌ ERROR DELETING HOUSE: \(error.localizedDescription)")
                print("Detailed error: \(error)")
            }
        }
    }
    
    // MARK: - Invitation Actions
    
    func fetchPendingInvites() async {
        do {
            let session = try await supabase.auth.session
            let userEmail = session.user.email ?? ""
            
            self.pendingInvites = try await supabase
                .from("invitations")
                .select()
                .eq("email", value: userEmail)
                .eq("status", value: "pending")
                .execute()
                .value
        } catch {
            print("Error fetching invites: \(error)")
        }
    }
    
    func inviteUser(email: String, to houseId: UUID) async {
        do {
            let newInvite = Invitation(
                house_id: houseId,
                email: email.lowercased().trimmingCharacters(in: .whitespacesAndNewlines),
                status: "pending"
            )
            
            try await supabase
                .from("invitations")
                .insert(newInvite)
                .execute()
        } catch {
            print("Error sending invite: \(error)")
        }
    }
    
    func acceptInvite(invite: Invitation) async {
        do {
            let session = try await supabase.auth.session
            let userId = session.user.id
            guard let inviteId = invite.id else { return }
            
            // 1. Join the house
            let memberData = [
                "house_id": invite.house_id.uuidString,
                "user_id": userId.uuidString,
                "role": "member"
            ]
            try await supabase
                .from("house_members")
                .insert(memberData)
                .execute()
            
            // 2. Update invite status
            try await supabase
                .from("invitations")
                .update(["status": "accepted"])
                .eq("id", value: inviteId)
                .execute()
            
            // 3. Refresh Data
            await fetchHouses()
            await fetchPendingInvites()
            
        } catch {
            print("Error accepting invite: \(error)")
        }
    }
    
    func rejectInvite(invite: Invitation) async {
        do {
            guard let inviteId = invite.id else { return }
            
            // Mark the invitation as rejected in the database
            try await supabase
                .from("invitations")
                .update(["status": "rejected"])
                .eq("id", value: inviteId)
                .execute()
            
            // Refresh the user's pending invites so it disappears from their screen
            await fetchHouses()
            await fetchPendingInvites()
            
        } catch {
            print("Error rejecting invite: \(error)")
        }
    }
    
    // MARK: - Manage Invites & Members
        
    func fetchHouseDetails(for houseId: UUID) async {
        let session = try? await supabase.auth.session
        self.currentUserId = session?.user.id
        
        // 1. Fetch Members safely
        do {
            let memberResponse: [HouseMember] = try await supabase
                .rpc("get_house_members_with_emails", params: ["p_house_id": houseId.uuidString])
                .execute()
                .value
            self.currentHouseMembers = memberResponse
        } catch {
            print("❌ Error fetching members (Did you run the SQL RPC script?): \(error)")
        }
        
        // 2. Fetch Invites safely
        do {
            self.currentHouseInvites = try await supabase
                .from("invitations")
                .select()
                .eq("house_id", value: houseId)
                .order("created_at", ascending: false)
                .execute()
                .value
        } catch {
            print("❌ Error fetching invites: \(error)")
        }
    }
    
    func checkUserExists(email: String) async -> Bool {
        do {
            let exists: Bool = try await supabase
                .rpc("check_user_exists", params: ["lookup_email": email])
                .execute()
                .value
            return exists
        } catch {
            print("Error checking user: \(error)")
            return false
        }
    }
    
    func removeMember(memberId: UUID) async {
        do {
            try await supabase
                .from("house_members")
                .delete()
                .eq("id", value: memberId)
                .execute()
            
            // Remove from UI list
            self.currentHouseMembers.removeAll { $0.id == memberId }
        } catch {
            print("Error removing member: \(error)")
        }
    }
}
