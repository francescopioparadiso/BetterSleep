import SwiftUI

private func flagForHouse(_ name: String) -> String {
    let n = name.lowercased()
    // Italian cities
    if n.contains("roma") || n.contains("rome") || n.contains("milano") || n.contains("milan")
        || n.contains("torino") || n.contains("turin") || n.contains("napol") || n.contains("firenz")
        || n.contains("florence") || n.contains("venezia") || n.contains("venice") || n.contains("bologna")
        || n.contains("italia") || n.contains("italy") || n.contains("genova") || n.contains("palermo")
        || n.contains("bari") || n.contains("catania") { return "🇮🇹" }
    // UK
    if n.contains("london") || n.contains("manchester") || n.contains("liverpool") || n.contains("birmingham")
        || n.contains("uk") || n.contains("england") || n.contains("edinburgh") || n.contains("scotland") { return "🇬🇧" }
    // USA
    if n.contains("new york") || n.contains("los angeles") || n.contains("chicago") || n.contains("miami")
        || n.contains("san francisco") || n.contains("boston") || n.contains("seattle")
        || n.contains("usa") || n.contains("america") { return "🇺🇸" }
    // France
    if n.contains("paris") || n.contains("lyon") || n.contains("marseille") || n.contains("france")
        || n.contains("nice") || n.contains("toulouse") { return "🇫🇷" }
    // Germany
    if n.contains("berlin") || n.contains("munich") || n.contains("münchen") || n.contains("hamburg")
        || n.contains("frankfurt") || n.contains("german") { return "🇩🇪" }
    // Spain
    if n.contains("madrid") || n.contains("barcelona") || n.contains("spain") || n.contains("sevilla")
        || n.contains("valencia") { return "🇪🇸" }
    // Japan
    if n.contains("tokyo") || n.contains("osaka") || n.contains("japan") || n.contains("kyoto") { return "🇯🇵" }
    // Default house emoji
    return "🏠"
}

struct HouseView: View {
    @StateObject private var viewModel = HouseModel()
    @StateObject private var roomModel = RoomModel()
    
    @State private var showingAddHouse = false
    @State private var newHouseName = ""
    @State private var showingProfile = false
    @State private var activeRoomsByHouse: [Int: Bool] = [:]
    
    private var currentUserId: Int? {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            return id
        }
        return nil
    }
    
    var body: some View {
        NavigationView {
            VStack {
                if viewModel.isLoading {
                    ProgressView("Loading your homes...")
                } else if viewModel.houses.isEmpty && viewModel.pendingInvites.isEmpty {
                    ContentUnavailableView(
                        "No Homes Found",
                        systemImage: "house.circle",
                        description: Text("Tap the + button in the top right to create your first smart home.")
                    )
                } else {
                    List {
                        // MARK: - Pending Invites
                        if !viewModel.pendingInvites.isEmpty {
                            Section(header: Text("Pending Invitations").fontDesign(.rounded).fontWeight(.semibold)) {
                                ForEach(viewModel.pendingInvites) { invite in
                                    HStack {
                                        VStack(alignment: .leading) {
                                            Text("Home Invitation")
                                                .font(.headline)
                                                .fontDesign(.rounded)
                                            Text("Tap accept to join this home.")
                                                .font(.caption)
                                                .fontDesign(.rounded)
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        
                                        Button(action: {
                                            Task { await viewModel.rejectInvite(invite: invite) }
                                        }) {
                                            Text("Decline")
                                                .fontDesign(.rounded)
                                        }
                                        .buttonStyle(.glassProminent)
                                        .foregroundStyle(Color.red)
                                        .tint(Color.red.opacity(0.15))
                                        
                                        Button(action: {
                                            Task { await viewModel.acceptInvite(invite: invite) }
                                        }) {
                                            Text("Accept")
                                                .fontDesign(.rounded)
                                        }
                                        .buttonStyle(.glassProminent)
                                        .foregroundStyle(Color.green)
                                        .tint(Color.green.opacity(0.15))
                                    }.padding(.vertical, 4)
                                }
                            }
                        }
                        
                        // MARK: - Homes Section
                        if !viewModel.houses.isEmpty {
                            Section(header: Text("My Homes").fontDesign(.rounded).fontWeight(.semibold)) {
                                ForEach(viewModel.houses) { house in
                                    NavigationLink(destination: RoomsView(house: house)) {
                                        HStack(spacing: 14) {
                                            if activeRoomsByHouse[house.id ?? 0] == true {
                                                Image(systemName: "star.fill")
                                                    .font(.title)
                                                    .foregroundColor(.yellow)
                                                    .padding(6)
                                                    .shadow(color: .yellow, radius: 20, x: 0, y: 0)
                                            } else {
                                                Text(flagForHouse(house.name))
                                                    .font(.title)
                                            }
                                            
                                            Text(house.name)
                                                .font(.headline)
                                                .fontWeight(.semibold)
                                                .fontDesign(.rounded)
                                        }
                                        .padding(.vertical, 6)
                                    }
                                }
                                .onDelete { indexSet in
                                    Task { await viewModel.deleteHouse(at: indexSet) }
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Houses")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(action: { showingProfile = true }) {
                        Image(systemName: "person.fill")
                            .font(.title3)
                            .foregroundColor(.primary)
                    }
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: { showingAddHouse = true }) {
                        Image(systemName: "plus")
                    }
                    .buttonStyle(.glassProminent)
                }
            }
            .alert("Create a Home", isPresented: $showingAddHouse) {
                TextField("Insert the name of your home", text: $newHouseName)
                Button("Cancel", role: .cancel) { newHouseName = "" }
                Button("Create") {
                    Task {
                        await viewModel.addHouse(name: newHouseName)
                        newHouseName = ""
                    }
                }
                .buttonStyle(.glassProminent)
            }
            .sheet(isPresented: $showingProfile) {
                ProfileView()
            }
            .task {
                await viewModel.fetchHouses()
                await viewModel.fetchPendingInvites()
                if let userId = currentUserId {
                    await fetchActiveRooms(for: userId)
                }
            }
            .onAppear {
                Task {
                    if let userId = currentUserId {
                        await fetchActiveRooms(for: userId)
                    }
                }
            }
        }
    }
    
    private func fetchActiveRooms(for userId: Int) async {
        do {
            let base = try await CatalogClient.shared.getUserServiceURL()
            let url = URL(string: "\(base)/getActiveRoom?user_id=\(userId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            
            // Reset active rooms first
            await MainActor.run {
                activeRoomsByHouse.removeAll()
            }
            
            if let activeRoomData = json?["active_room"] as? [String: Any],
               let houseId = activeRoomData["house_id"] as? Int {
                await MainActor.run {
                    activeRoomsByHouse[houseId] = true
                }
            }
        } catch {
            print("Error fetching active room: \(error)")
        }
    }
}

#Preview {
    HouseView()
}
