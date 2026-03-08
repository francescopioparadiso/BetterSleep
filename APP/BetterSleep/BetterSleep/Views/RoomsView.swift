import SwiftUI

// MARK: - View Extension for conditional modifications
extension View {
    @ViewBuilder
    func `if`<Content: View>(_ condition: Bool, transform: (Self) -> Content) -> some View {
        if condition {
            transform(self)
        } else {
            self
        }
    }
}

func iconForRoom(_ name: String) -> String {
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
    @Environment(\.colorScheme) var colorScheme

    let house: House
    @StateObject private var roomModel = RoomModel()
    @StateObject private var invitationModel = InvitationModel()
    
    @State private var showingAddRoom = false
    @State private var showingMembers = false
    @State private var newRoomName = ""
    
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

    private var myRoom: Room? {
        roomModel.rooms.first { $0.user_id == currentUserId }
    }

    private var availableRooms: [Room] {
        roomModel.rooms.filter { $0.user_id == nil }
    }

    private var occupiedRooms: [Room] {
        roomModel.rooms.filter { $0.user_id != nil && $0.user_id != currentUserId }
    }
    
    var body: some View {
        List {
            // MARK: - My Room
            Section(header: Text("My Room")) {
                    if let room = myRoom {
                        myRoomRow(room)
                    } else {
                        HStack {
                            Spacer()
                            VStack(spacing: 8) {
                                Image(systemName: "person.crop.circle.badge.questionmark")
                                    .font(.largeTitle)
                                    .foregroundStyle(.secondary)
                                Text("No room assigned")
                                    .font(.subheadline)
                                    .fontDesign(.rounded)
                                    .foregroundStyle(.secondary)
                                Text("Swipe right on an available room to assign it to yourself")
                                    .font(.caption)
                                    .fontDesign(.rounded)
                                    .foregroundStyle(.tertiary)
                                    .multilineTextAlignment(.center)
                            }
                            .padding(.vertical, 20)
                            Spacer()
                        }
                    }
                }

            // MARK: - Available Rooms
            Section(header: Text("Available Rooms")) {
                if availableRooms.isEmpty {
                    HStack {
                        Spacer()
                        VStack(spacing: 8) {
                            Image(systemName: "bed.double.circle")
                                .font(.largeTitle)
                                .foregroundStyle(.secondary)
                            Text("No available rooms")
                                .font(.subheadline)
                                .fontDesign(.rounded)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 20)
                        Spacer()
                    }
                } else {
                    ForEach(availableRooms) { room in
                        roomRow(room)
                            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                                Button {
                                    Task {
                                        guard let roomId = room.id else { return }
                                        await roomModel.assignRoom(roomId: roomId, houseId: house.id!)
                                    }
                                } label: {
                                    Label("Assign to Me", systemImage: "person.crop.circle.badge.checkmark")
                                }
                                .tint(.indigo)
                            }
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                Button(role: .destructive) {
                                    Task {
                                        guard let roomId = room.id else { return }
                                        await roomModel.deleteRoom(roomId: roomId, houseId: house.id!)
                                    }
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                    }
                }
            }

            // MARK: - Occupied Rooms
            if !occupiedRooms.isEmpty {
                Section(header: Text("Occupied Rooms")) {
                    ForEach(occupiedRooms) { room in
                        roomRow(room)
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                Button(role: .destructive) {
                                    Task {
                                        guard let roomId = room.id else { return }
                                        await roomModel.deleteRoom(roomId: roomId, houseId: house.id!)
                                    }
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(house.name)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button(action: { showingMembers = true }) {
                    Image(systemName: "person.2")
                        .foregroundStyle(colorScheme == .dark ? Color.white : Color.black)
                }
                .buttonStyle(.glassProminent)
                .tint(colorScheme == .dark ? Color.black.opacity(0.1) : Color.white)
                .clipShape(.circle)
            }

            ToolbarItem(placement: .navigationBarTrailing) {
                Button(action: { showingAddRoom = true }) {
                    Image(systemName: "plus")
                }
                .buttonStyle(.glassProminent)
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
            if let currentUserId = currentUserId {
                await roomModel.fetchActiveRoom(for: currentUserId)
            }
        }
        .sheet(isPresented: $showingMembers) {
            MembersSheet(
                house: house,
                invitationModel: invitationModel,
                sortedMembers: sortedMembers,
                pendingInvites: pendingInvites,
                isCurrentUserOwner: isCurrentUserOwner,
                currentUserId: currentUserId
            )
        }
    }
    
    // MARK: - Room Row Helpers
    private func roomContent(_ room: Room) -> some View {
        HStack(spacing: 14) {
            if room.active {
                Image(systemName: "star.fill")
                    .font(.title)
                    .padding(6)
                    .foregroundColor(.yellow)
                    .shadow(color: .yellow, radius: 20, x: 0, y: 0)
            } else {
                Image(systemName: iconForRoom(room.name))
                    .font(.title)
                    .foregroundColor(.indigo)
                    .shadow(color: .indigo, radius: 20, x: 0, y: 0)
            }
            
            VStack(alignment: .leading, spacing: 3) {
                Text(room.name)
                    .font(.headline)
                    .fontWeight(.semibold)
                    .fontDesign(.rounded)

                if let uid = room.user_id {
                    let label = uid == currentUserId ? "Assigned to you" : "Occupied"
                    Text(label)
                        .font(.caption)
                        .fontDesign(.rounded)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Unassigned")
                        .font(.caption)
                        .fontDesign(.rounded)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(.vertical, 6)
    }

    @ViewBuilder
    private func myRoomRow(_ room: Room) -> some View {
        if let index = roomModel.rooms.firstIndex(where: { $0.id == room.id }) {
            NavigationLink(destination: SensorsView(house: house, room: $roomModel.rooms[index], roomModel: roomModel)) {
                roomContent(room)
            }
            .swipeActions(edge: .leading, allowsFullSwipe: true) {
                Button {
                    Task {
                        guard let roomId = room.id, let houseId = house.id else { return }
                        if room.active {
                            await roomModel.deactivateRoom(roomId: roomId, houseId: houseId)
                        } else {
                            await roomModel.setActiveRoom(roomId: roomId, houseId: houseId)
                        }
                    }
                } label: {
                    Label(room.active ? "Deactivate" : "Make Active", systemImage: room.active ? "star.slash.fill" : "star.fill")
                }
                .tint(room.active ? .gray : .yellow)
            }
            .swipeActions(edge: .leading, allowsFullSwipe: false) {
                Button {
                    Task {
                        guard let roomId = room.id, let houseId = house.id else { return }
                        await roomModel.unassignRoom(roomId: roomId, houseId: houseId)
                    }
                } label: {
                    Label("Unassign", systemImage: "person.crop.circle.badge.minus")
                }
                .tint(.orange)
            }
            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                Button(role: .destructive) {
                    Task {
                        guard let roomId = room.id, let houseId = house.id else { return }
                        await roomModel.deleteRoom(roomId: roomId, houseId: houseId)
                    }
                } label: {
                    Label("Delete", systemImage: "trash")
                }
            }
        }
    }

    private func roomRow(_ room: Room) -> some View {
        NavigationLink(destination: {
            if let index = roomModel.rooms.firstIndex(where: { $0.id == room.id }) {
                SensorsView(house: house, room: $roomModel.rooms[index], roomModel: roomModel)
            }
        }) {
            roomContent(room)
        }
    }
}

// MARK: - Members Sheet
struct MembersSheet: View {
    let house: House
    @ObservedObject var invitationModel: InvitationModel
    let sortedMembers: [HouseMember]
    let pendingInvites: [Invitation]
    let isCurrentUserOwner: Bool
    let currentUserId: Int?

    @State private var emailToInvite = ""
    @State private var isSending = false
    @State private var toastAnimation = Animation.bouncy(duration: 0.5)
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                List {
                    // MARK: - Active Members
                    Section(header: Text("Active Members")) {
                        ForEach(sortedMembers) { member in
                            HStack {
                                Image(systemName: member.role == 0 ? "star.fill" : "person.fill")
                                    .foregroundColor(member.role == 0 ? .yellow : .blue)
                                    .frame(width: 30)

                                VStack(alignment: .leading) {
                                    Text(member.email ?? "Unknown User")
                                        .font(.body)
                                        .fontDesign(.rounded)
                                    Text(member.user_id == currentUserId ? "You" : "Housemate")
                                        .font(.caption)
                                        .fontDesign(.rounded)
                                        .foregroundColor(.secondary)
                                }
                                Spacer()

                                Button {} label: {
                                    Text(member.role == 0 ? "Owner" : "Guest")
                                        .fontDesign(.rounded)
                                }
                                .buttonStyle(.glassProminent)
                                .foregroundStyle(member.role == 0 ? Color.yellow : Color.blue)
                                .tint((member.role == 0 ? Color.yellow : Color.blue).opacity(0.15))
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
                    }

                    // MARK: - Pending Members
                    Section(header: Text("Pending Members")) {
                        if pendingInvites.isEmpty {
                            HStack {
                                Spacer()
                                Text("No pending invitations")
                                    .font(.subheadline)
                                    .fontDesign(.rounded)
                                    .foregroundStyle(.secondary)
                                Spacer()
                            }
                            .padding(.vertical, 20)
                        } else {
                            ForEach(pendingInvites) { invite in
                                HStack {
                                    Image(systemName: "questionmark.circle.fill")
                                        .foregroundColor(.orange)
                                        .frame(width: 30)
                                    Text(invite.email)
                                        .foregroundColor(.primary)

                                    Spacer()

                                    Button {} label: {
                                        Text("Pending")
                                            .fontDesign(.rounded)
                                    }
                                    .buttonStyle(.glassProminent)
                                    .foregroundStyle(Color.orange)
                                    .tint(Color.orange.opacity(0.15))
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
                        }
                    }

                    // MARK: - Invite
                    Section(header: Text("Invite")) {
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
                                        .fontDesign(.rounded)
                                }
                                .buttonStyle(.glassProminent)
                                .disabled(emailToInvite.isEmpty || !emailToInvite.contains("@"))
                                .tint((emailToInvite.isEmpty || !emailToInvite.contains("@") ? Color.gray : Color.blue).opacity(0.15))
                                .foregroundStyle(emailToInvite.isEmpty || !emailToInvite.contains("@") ? Color.gray : Color.blue)
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
                            .font(.subheadline)
                            .fontWeight(.medium)
                            .fontDesign(.rounded)
                            .lineLimit(2)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .foregroundStyle(Color.white)
                    .background(Color.red.opacity(0.8))
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
            .navigationTitle("Members")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { dismiss() }
                        .fontDesign(.rounded)
                }
            }
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
