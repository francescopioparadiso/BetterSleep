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
    @StateObject private var roomModel: RoomModel
    @StateObject private var invitationModel: InvitationModel
    private let shouldAutoLoad: Bool
    
    @State private var showingMembers = false
    @State private var newRoomName = ""

    init(house: House, shouldAutoLoad: Bool = true) {
        self.house = house
        _roomModel = StateObject(wrappedValue: RoomModel())
        _invitationModel = StateObject(wrappedValue: InvitationModel())
        self.shouldAutoLoad = shouldAutoLoad
    }

    init(house: House, roomModel: RoomModel, invitationModel: InvitationModel, shouldAutoLoad: Bool = true) {
        self.house = house
        _roomModel = StateObject(wrappedValue: roomModel)
        _invitationModel = StateObject(wrappedValue: invitationModel)
        self.shouldAutoLoad = shouldAutoLoad
    }
    
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
            return (a.email ?? "").localizedCaseInsensitiveCompare(b.email ?? "") == .orderedAscending
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

            // MARK: - Rooms
            Section(header: Text("Rooms")) {
                // Available rooms first
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

                // Occupied rooms after available rooms
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

                // Keep add-room row at the end of Rooms section.
                addRoomRow
            }
        }
        .listStyle(.insetGrouped)
        .refreshable {
            await refreshData()
        }
        .navigationTitle(house.name)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Button {
                    showingMembers = true
                } label: {
                    HStack {
                        Image(systemName: "person.2")

                        Text("Members")
                            .fontDesign(.rounded)
                    }
                    .buttonStyle(.glassProminent)
                    .foregroundStyle(.primary)
                    .tint(colorScheme == .dark ? Color.black.opacity(0.1) : Color.white)
                }
            }
        }
        .task {
            if shouldAutoLoad {
                await refreshData()
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

    private func refreshData() async {
        guard let houseId = house.id else { return }
        await roomModel.fetchRooms(for: houseId)
        await invitationModel.fetchHouseDetails(for: houseId)
        if let currentUserId = currentUserId {
            await roomModel.fetchActiveRoom(for: currentUserId)
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
                    .shadow(color: .yellow, radius: 10, x: 0, y: 0)
            } else {
                Image(systemName: iconForRoom(room.name))
                    .font(.title)
                    .foregroundColor(room.user_id == nil ? Color.green : Color.red)
                    .shadow(color: room.user_id == nil ? Color.green.opacity(0.65) : Color.red.opacity(0.65), radius: 10, x: 0, y: 0)
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

    private var addRoomRow: some View {
        HStack(spacing: 14) {
            Image(systemName: iconForRoom(newRoomName.isEmpty ? "bedroom" : newRoomName))
                .font(.title)
                .foregroundColor(.indigo)
                .shadow(color: .indigo.opacity(0.65), radius: 10, x: 0, y: 0)

            TextField("Type your new room name", text: $newRoomName)
                .font(.headline)
                .fontWeight(.semibold)
                .fontDesign(.rounded)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled(true)
                .submitLabel(.done)
                .onSubmit {
                    Task { await createRoomFromInput() }
                }
        }
        .padding(.vertical, 6)
    }

    private func createRoomFromInput() async {
        let trimmed = newRoomName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let houseId = house.id else { return }
        await roomModel.addRoom(name: trimmed, houseId: houseId)
        newRoomName = ""
    }
}

private func makeRoomPreviewModel(rooms: [Room]) -> RoomModel {
    let vm = RoomModel()
    vm.rooms = rooms
    return vm
}

private func makeInvitationPreviewModel(members: [HouseMember], invites: [Invitation]) -> InvitationModel {
    let vm = InvitationModel()
    vm.currentHouseMembers = members
    vm.currentHouseInvites = invites
    return vm
}

private let previewHouse = House(id: 1, name: "Torino Home", created_at: nil)

#Preview("No Rooms") {
    RoomsView(
        house: previewHouse,
        roomModel: makeRoomPreviewModel(rooms: []),
        invitationModel: makeInvitationPreviewModel(members: [], invites: []),
        shouldAutoLoad: false
    )
}

#Preview("My Room + Available") {
    RoomsView(
        house: previewHouse,
        roomModel: makeRoomPreviewModel(rooms: [
            Room(id: 1, house_id: 1, name: "Master Bedroom", user_id: 42, created_at: nil, temperature_night: 18, temperature_morning: 22, light_night: 10, light_morning: 90, active: true),
            Room(id: 2, house_id: 1, name: "Guest Room", user_id: nil, created_at: nil, temperature_night: nil, temperature_morning: nil, light_night: nil, light_morning: nil, active: false)
        ]),
        invitationModel: makeInvitationPreviewModel(
            members: [HouseMember(id: 1, house_id: 1, user_id: 42, role: 0, email: "owner@mail.com")],
            invites: []
        ),
        shouldAutoLoad: false
    )
}

#Preview("Available + Occupied") {
    RoomsView(
        house: previewHouse,
        roomModel: makeRoomPreviewModel(rooms: [
            Room(id: 3, house_id: 1, name: "Kitchen", user_id: nil, created_at: nil, temperature_night: nil, temperature_morning: nil, light_night: nil, light_morning: nil, active: false),
            Room(id: 4, house_id: 1, name: "Office", user_id: 7, created_at: nil, temperature_night: nil, temperature_morning: nil, light_night: nil, light_morning: nil, active: false)
        ]),
        invitationModel: makeInvitationPreviewModel(
            members: [HouseMember(id: 2, house_id: 1, user_id: 7, role: 1, email: "guest@mail.com")],
            invites: []
        ),
        shouldAutoLoad: false
    )
}

#Preview("Pending Invites") {
    RoomsView(
        house: previewHouse,
        roomModel: makeRoomPreviewModel(rooms: [
            Room(id: 5, house_id: 1, name: "Living Room", user_id: nil, created_at: nil, temperature_night: nil, temperature_morning: nil, light_night: nil, light_morning: nil, active: false)
        ]),
        invitationModel: makeInvitationPreviewModel(
            members: [HouseMember(id: 1, house_id: 1, user_id: 42, role: 0, email: "owner@mail.com")],
            invites: [Invitation(id: 1, house_id: 1, email: "new.user@mail.com", status: 0, created_at: nil)]
        ),
        shouldAutoLoad: false
    )
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

    private var owners: [HouseMember] {
        sortedMembers.filter { $0.role == 0 }
    }

    private var guests: [HouseMember] {
        sortedMembers.filter { $0.role != 0 }
    }

    // "First guest who accepted first" -> earliest guest by member id when available.
    private var firstAcceptedGuest: HouseMember? {
        guests.min { (lhs, rhs) in
            (lhs.id ?? Int.max) < (rhs.id ?? Int.max)
        }
    }

    private var remainingGuestsAlphabetical: [HouseMember] {
        let firstId = firstAcceptedGuest?.id
        return guests
            .filter { $0.id != firstId }
            .sorted { (a, b) in
                (a.email ?? "").localizedCaseInsensitiveCompare(b.email ?? "") == .orderedAscending
            }
    }

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                List {
                    // 1) Owners first
                    ForEach(owners) { member in
                        memberRow(member)
                    }

                    // 2) First accepted guest
                    if let firstAcceptedGuest {
                        memberRow(firstAcceptedGuest)
                    }

                    // 3) Pending invites
                    ForEach(pendingInvites) { invite in
                        HStack {
                            Image(systemName: "questionmark.circle.fill")
                                .font(.title3)
                                .foregroundColor(.orange)
                                .shadow(color: .orange.opacity(0.45), radius: 6, x: 0, y: 0)

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

                    // 4) Remaining guests alphabetically
                    ForEach(remainingGuestsAlphabetical) { member in
                        memberRow(member)
                    }

                    // MARK: - Invite row (always last)
                    HStack {
                        Image(systemName: "arrowshape.turn.up.right.fill")
                            .font(.title3)
                            .foregroundColor(.blue)
                            .shadow(color: .blue.opacity(0.45), radius: 6, x: 0, y: 0)

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
                .listStyle(.insetGrouped)
                .refreshable {
                    guard let houseId = house.id else { return }
                    await invitationModel.fetchHouseDetails(for: houseId)
                }

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

    @ViewBuilder
    private func memberRow(_ member: HouseMember) -> some View {
        HStack {
            Image(systemName: member.role == 0 ? "star.fill" : "person.fill")
                .font(.title3)
                .foregroundColor(member.role == 0 ? .yellow : .blue)
                .shadow(color: member.role == 0 ? Color.yellow.opacity(0.45) : Color.blue.opacity(0.45), radius: 6, x: 0, y: 0)

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
