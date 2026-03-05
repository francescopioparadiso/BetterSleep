import SwiftUI

private func iconForRoom(_ name: String) -> String {
    let n = name.lowercased()
    if n.contains("bed")    { return "bed.double.fill" }
    if n.contains("bath")   { return "shower.fill" }
    if n.contains("kitchen") || n.contains("cucina") { return "fork.knife" }
    if n.contains("living") || n.contains("lounge") || n.contains("sogg") { return "sofa.fill" }
    if n.contains("office") || n.contains("studio") || n.contains("study") { return "desktopcomputer" }
    if n.contains("garage") { return "car.fill" }
    if n.contains("garden") || n.contains("giardino") || n.contains("balcon") || n.contains("terrac") { return "leaf.fill" }
    if n.contains("laundry") || n.contains("lavanderia") { return "washer.fill" }
    if n.contains("dining") || n.contains("pranzo") { return "wineglass.fill" }
    if n.contains("closet") || n.contains("wardrobe") { return "door.left.hand.closed" }
    if n.contains("gym") || n.contains("palestra") { return "dumbbell.fill" }
    if n.contains("kid") || n.contains("child") || n.contains("bambin") { return "teddybear.fill" }
    if n.contains("guest") || n.contains("ospit") { return "person.fill" }
    if n.contains("attic") || n.contains("mansard") || n.contains("soffitta") { return "triangle.fill" }
    if n.contains("basement") || n.contains("cantina") { return "stairs" }
    if n.contains("hall") || n.contains("entry") || n.contains("ingresso") || n.contains("corridor") { return "door.left.hand.open" }
    return "bed.double.fill"
}

struct RoomsView: View {
    let house: House
    @StateObject private var roomModel = RoomModel()
    @StateObject private var invitationModel = InvitationModel()
    
    @State private var showingAddRoom = false
    @State private var newRoomName = ""
    @State private var emailToInvite = ""
    @State private var isSending = false
    @State private var toastAnimation = Animation.bouncy(duration: 0.5)
    
    private var currentUserId: Int? {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) { return id }
        return nil
    }
    
    private var isCurrentUserOwner: Bool {
        invitationModel.currentHouseMembers.first(where: { $0.user_id == currentUserId })?.role == 0
    }
    
    private var sortedMembers: [HouseMember] {
        invitationModel.currentHouseMembers.sorted { a, b in
            if a.role == 0 { return true }
            if b.role == 0 { return false }
            return (a.email ?? "") < (b.email ?? "")
        }
    }
    
    private var pendingInvites: [Invitation] {
        invitationModel.currentHouseInvites.filter { $0.status == 0 }
    }
    
    var body: some View {
        ZStack(alignment: .top) {
            List {
                // MARK: - Rooms
                Section(header: Text("Rooms")) {
                    if roomModel.rooms.isEmpty {
                        HStack {
                            Spacer()
                            VStack(spacing: 8) {
                                Image(systemName: "bed.double.circle")
                                    .font(.largeTitle)
                                    .foregroundStyle(.secondary)
                                Text("No rooms yet")
                                    .font(.subheadline)
                                    .foregroundStyle(.secondary)
                            }
                            .padding(.vertical, 20)
                            Spacer()
                        }
                        .listRowBackground(Color.clear)
                    } else {
                        ForEach(roomModel.rooms) { room in
                            HStack(spacing: 14) {
                                Image(systemName: iconForRoom(room.name))
                                    .font(.title2)
                                    .foregroundColor(.indigo)
                                    .frame(width: 36)
                                
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(room.name)
                                        .font(.system(size: 17, weight: .semibold, design: .rounded))
                                    Text("0 sensors")
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                }
                                
                                Spacer()
                                
                                Image(systemName: "chevron.right")
                                    .font(.caption.weight(.semibold))
                                    .foregroundColor(.secondary)
                            }
                            .padding(.vertical, 6)
                        }
                        .onDelete { offsets in
                            Task {
                                for index in offsets {
                                    if let roomId = roomModel.rooms[index].id {
                                        await roomModel.deleteRoom(roomId: roomId, houseId: house.id!)
                                    }
                                }
                            }
                        }
                    }
                }
                
                // MARK: - Members
                Section(header: Text("Members")) {
                    ForEach(sortedMembers) { member in
                        HStack {
                            Image(systemName: member.role == 0 ? "star.fill" : "person.fill")
                                .foregroundColor(member.role == 0 ? .yellow : .blue)
                                .frame(width: 30)
                            
                            VStack(alignment: .leading) {
                                Text(member.email ?? "Unknown User")
                                    .font(.body)
                                Text(member.user_id == currentUserId ? "You" : "Housemate")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                            Spacer()
                            
                            Text(member.role == 0 ? "Owner" : "Guest")
                                .font(.caption).bold()
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(member.role == 0 ? Color.yellow.opacity(0.2) : Color.gray.opacity(0.2))
                                .foregroundColor(member.role == 0 ? .yellow : .primary)
                                .cornerRadius(8)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            if isCurrentUserOwner && member.user_id != currentUserId {
                                Button(role: .destructive) {
                                    Task {
                                        if let id = member.id {
                                            await invitationModel.removeMember(memberId: id)
                                        }
                                    }
                                } label: {
                                    Label("Remove", systemImage: "trash")
                                }
                            }
                        }
                    }
                    
                    // Pending invites inline
                    ForEach(pendingInvites) { invite in
                        HStack {
                            Image(systemName: "questionmark.circle.fill")
                                .foregroundColor(.orange)
                                .frame(width: 30)
                            Text(invite.email)
                                .foregroundColor(.primary)
                            Spacer()
                            Text("Pending")
                                .font(.caption).bold()
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(Color.orange.opacity(0.2))
                                .foregroundColor(.orange)
                                .cornerRadius(8)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                            if isCurrentUserOwner {
                                Button(role: .destructive) {
                                    Task {
                                        if let id = invite.id {
                                            await invitationModel.deleteInvite(inviteId: id)
                                            await invitationModel.fetchHouseDetails(for: house.id!)
                                        }
                                    }
                                } label: {
                                    Label("Cancel", systemImage: "xmark.circle")
                                }
                            }
                        }
                    }
                    
                    // Invite row
                    HStack {
                        Image(systemName: "envelope.badge.fill")
                            .foregroundColor(.blue)
                            .frame(width: 30)
                        TextField("Invite housemate via email...", text: $emailToInvite)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        
                        if isSending {
                            ProgressView()
                        } else {
                            Button(action: sendInvite) {
                                Text("Send")
                                    .font(.subheadline.weight(.semibold))
                            }
                            .disabled(emailToInvite.isEmpty || !emailToInvite.contains("@"))
                            .buttonStyle(.borderedProminent)
                            .tint(emailToInvite.isEmpty || !emailToInvite.contains("@") ? .gray : .blue)
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
            .listStyle(.insetGrouped)
            
            // MARK: - Error Toast
            if let errorMessage = invitationModel.errorMessage {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    Text(errorMessage)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(2)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .foregroundStyle(.white)
                .background(Color.red.opacity(0.85))
                .clipShape(.rect(cornerRadius: 24))
                .shadow(color: Color.red, radius: 30, x: 0, y: 0)
                .transition(.asymmetric(
                    insertion: .move(edge: .top).combined(with: .opacity).combined(with: .scale(scale: 0.5)),
                    removal: .move(edge: .top).combined(with: .opacity).combined(with: .scale(scale: 0.5))
                ))
                .zIndex(1)
                .onAppear {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) {
                        withAnimation(toastAnimation) {
                            invitationModel.errorMessage = nil
                        }
                    }
                }
            }
        }
        .animation(toastAnimation, value: invitationModel.errorMessage)
        .navigationTitle(house.name)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button(action: { showingAddRoom = true }) {
                    Image(systemName: "plus")
                }
            }
        }
        .alert("New Room", isPresented: $showingAddRoom) {
            TextField("Room name", text: $newRoomName)
            Button("Cancel", role: .cancel) { newRoomName = "" }
            Button("Add") {
                Task {
                    await roomModel.addRoom(name: newRoomName, houseId: house.id!)
                    newRoomName = ""
                }
            }
        }
        .task {
            guard let houseId = house.id else { return }
            await roomModel.fetchRooms(for: houseId)
            await invitationModel.fetchHouseDetails(for: houseId)
        }
    }
    
    private func sendInvite() {
        Task {
            isSending = true
            invitationModel.errorMessage = nil
            let userExists = await invitationModel.checkUserExists(email: emailToInvite.lowercased())
            if userExists {
                await invitationModel.inviteUser(email: emailToInvite, to: house.id!)
                emailToInvite = ""
                await invitationModel.fetchHouseDetails(for: house.id!)
            } else {
                withAnimation(toastAnimation) {
                    invitationModel.errorMessage = "User not found. They must sign up first."
                }
            }
            isSending = false
        }
    }
}
