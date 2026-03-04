import SwiftUI

struct RoomsListView: View {
    var house: House
    @StateObject private var viewModel = RoomsViewModel()
    @State private var showingAddRoom = false
    @State private var showingInvites = false
    @State private var newRoomName = ""
    
    var body: some View {
        Group {
            if viewModel.isLoading {
                ProgressView()
            } else if viewModel.rooms.isEmpty {
                ContentUnavailableView(
                    "No Rooms Yet",
                    systemImage: "door.left.hand.closed",
                    description: Text("Add a room to start configuring your sensors.")
                )
            } else {
                List {
                    // --- SECTION 1: YOUR ROOM ---
                    Section(header: Text("Your Room"), footer: Text("You can only occupy one room at a time. Swipe to leave so it can be deleted.")) {
//                        if let myRoom = viewModel.myRoom {
//                            NavigationLink(destination: SensorsListView(room: myRoom)) {
//                                VStack(alignment: .leading, spacing: 4) {
//                                    HStack {
//                                        Image(systemName: "bed.double.fill").foregroundColor(.blue)
//                                        Text(myRoom.name).font(.headline)
//                                    }
//                                    Text("Occupied by You")
//                                        .font(.caption)
//                                        .foregroundColor(.secondary)
//                                }
//                            }
//                            // Swipe Left to Leave (No Delete Button Here!)
//                            .swipeActions(edge: .leading) {
//                                Button(role: .destructive) {
//                                    Task { await viewModel.leaveRoom(myRoom) }
//                                } label: {
//                                    Label("Leave", systemImage: "rectangle.portrait.and.arrow.right")
//                                }
//                                .tint(.orange)
//                            }
//                        } else {
//                            Text("You are not assigned to a room yet. Swipe right on an available room to join it.")
//                                .font(.subheadline)
//                                .foregroundColor(.secondary)
//                        }
                    }
                    
                    // --- SECTION 2: AVAILABLE ROOMS ---
//                    if !viewModel.availableRooms.isEmpty {
//                        Section(header: Text("Available Rooms")) {
//                            ForEach(viewModel.availableRooms) { room in
//                                NavigationLink(destination: SensorsListView(room: room)) {
//                                    VStack(alignment: .leading, spacing: 4) {
//                                        Text(room.name).font(.headline)
//                                        Text("Empty")
//                                            .font(.caption)
//                                            .foregroundColor(.green)
//                                    }
//                                }
//                                // Swipe Left to Join
//                                .swipeActions(edge: .leading) {
//                                    Button {
//                                        Task { await viewModel.joinRoom(room) }
//                                    } label: {
//                                        Label("Join", systemImage: "person.badge.plus")
//                                    }
//                                    .tint(.green)
//                                }
//                                // Swipe Right to Delete (Allowed because it's empty)
//                                .swipeActions(edge: .trailing) {
//                                    Button(role: .destructive) {
//                                        Task { await viewModel.deleteRoom(room) }
//                                    } label: {
//                                        Label("Delete", systemImage: "trash")
//                                    }
//                                }
//                            }
//                        }
//                    }
                    
                    // --- SECTION 3: OTHER OCCUPIED ROOMS ---
//                    if !viewModel.occupiedRooms.isEmpty {
//                        Section(header: Text("Occupied Rooms"), footer: Text("You cannot join or delete rooms occupied by others.")) {
//                            ForEach(viewModel.occupiedRooms) { room in
//                                NavigationLink(destination: SensorsListView(room: room)) {
//                                    VStack(alignment: .leading, spacing: 4) {
//                                        Text(room.name).font(.headline)
//                                        HStack {
//                                            Image(systemName: "person.fill").font(.caption2)
//                                            Text(viewModel.ownerEmail(for: room)).font(.caption)
//                                        }
//                                        .foregroundColor(.secondary)
//                                    }
//                                }
//                                // NO SWIPE ACTIONS! They belong to other users.
//                            }
//                        }
//                    }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle(house.name)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                HStack {
                    Button(action: { showingInvites = true }) { Image(systemName: "person.badge.plus") }
                    Button(action: { showingAddRoom = true }) { Image(systemName: "plus") }
                }
            }
        }
//        .alert("New Room", isPresented: $showingAddRoom) {
//            TextField("Room Name", text: $newRoomName)
//            Button("Cancel", role: .cancel) { newRoomName = "" }
//            Button("Add") {
//                Task {
//                    if let hid = house.id { await viewModel.addRoom(name: newRoomName, to: hid) }
//                    newRoomName = ""
//                }
//            }
//        }
//        .sheet(isPresented: $showingInvites) {
//            if let hid = house.id { ManageInvitesView(houseId: hid) }
//        }
//        // UPGRADED: Fetch both rooms and members
//        .task {
//            if let hid = house.id { await viewModel.fetchRoomsAndMembers(for: hid) }
//        }
    }
}
