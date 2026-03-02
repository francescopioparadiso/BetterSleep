import Foundation
import Supabase
import Combine

@MainActor
class RoomsViewModel: ObservableObject {
    @Published var rooms: [Room] = []
    @Published var houseMembers: [HouseMember] = [] // Added to fetch emails
    @Published var isLoading = false
    
    // Get the current logged-in user's ID
    var currentUserId: UUID? {
        supabase.auth.currentUser?.id
    }
    
    // Computed property: The single room the user is in
    var myRoom: Room? {
        guard let uid = currentUserId else { return nil }
        return rooms.first { $0.user_id == uid }
    }
    
    // Computed property: Empty rooms
    var availableRooms: [Room] {
        return rooms.filter { $0.user_id == nil }
    }
    
    // Computed property: Rooms occupied by OTHER housemates
    var occupiedRooms: [Room] {
        guard let uid = currentUserId else { return [] }
        return rooms.filter { $0.user_id != nil && $0.user_id != uid }
    }
    
    // Helper to find the email of the room's occupant
    func ownerEmail(for room: Room) -> String {
        guard let uid = room.user_id else { return "Empty" }
        return houseMembers.first { $0.user_id == uid }?.email ?? "Unknown Housemate"
    }
    
    func fetchRoomsAndMembers(for houseId: UUID) async {
        isLoading = true
        do {
            // 1. Fetch the rooms
            self.rooms = try await supabase
                .from("rooms")
                .select()
                .eq("house_id", value: houseId)
                .order("created_at", ascending: true)
                .execute()
                .value
                
            // 2. Fetch the house members using the RPC (so we get the emails!)
            self.houseMembers = try await supabase
                .rpc("get_house_members_with_emails", params: ["p_house_id": houseId.uuidString])
                .execute()
                .value
        } catch {
            print("❌ Error fetching rooms/members: \(error)")
        }
        isLoading = false
    }
    
    func addRoom(name: String, to houseId: UUID) async {
        do {
            let newRoomId = UUID()
            let newRoom = Room(id: newRoomId, house_id: houseId, name: name, user_id: nil)
            
            try await supabase
                .from("rooms")
                .insert(newRoom)
                .execute()
            
            self.rooms.append(newRoom)
        } catch {
            print("❌ Error adding room: \(error)")
        }
    }
    
    func deleteRoom(_ room: Room) async {
        guard let roomId = room.id else { return }
        
        // SAFETY CHECK: Prevent deleting occupied rooms
        guard room.user_id == nil else {
            print("❌ Cannot delete an occupied room!")
            return
        }
        
        do {
            try await supabase
                .from("rooms")
                .delete()
                .eq("id", value: roomId)
                .execute()
            
            self.rooms.removeAll(where: { $0.id == roomId })
        } catch {
            print("❌ Error deleting room: \(error)")
        }
    }
    
    func joinRoom(_ newRoom: Room) async {
        guard let userId = currentUserId else { return }
        
        if let currentRoom = myRoom {
            if currentRoom.id == newRoom.id { return }
            var updatedOldRoom = currentRoom
            updatedOldRoom.user_id = nil
            do {
                if let rid = updatedOldRoom.id {
                    try await supabase.from("rooms").update(updatedOldRoom).eq("id", value: rid).execute()
                    if let index = rooms.firstIndex(where: { $0.id == rid }) { rooms[index] = updatedOldRoom }
                }
            } catch { print("❌ Error leaving old room: \(error)") }
        }
        
        var updatedNewRoom = newRoom
        updatedNewRoom.user_id = userId
        do {
            if let rid = updatedNewRoom.id {
                try await supabase.from("rooms").update(updatedNewRoom).eq("id", value: rid).execute()
                if let index = rooms.firstIndex(where: { $0.id == rid }) { rooms[index] = updatedNewRoom }
            }
        } catch { print("❌ Error joining new room: \(error)") }
    }
    
    func leaveRoom(_ room: Room) async {
        var updatedRoom = room
        updatedRoom.user_id = nil
        do {
            if let rid = updatedRoom.id {
                try await supabase.from("rooms").update(updatedRoom).eq("id", value: rid).execute()
                if let index = rooms.firstIndex(where: { $0.id == rid }) { rooms[index] = updatedRoom }
            }
        } catch { print("❌ Error leaving room: \(error)") }
    }
}
