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
    
    @State private var showingAddHouse = false
    @State private var newHouseName = ""
    @State private var showingProfile = false
    
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
                            Section(header: Text("Pending Invitations").foregroundColor(.blue)) {
                                ForEach(viewModel.pendingInvites) { invite in
                                    HStack {
                                        VStack(alignment: .leading) {
                                            Text("Home Invitation").font(.headline)
                                            Text("Tap accept to join this home.").font(.caption).foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        
                                        Button(action: {
                                            Task { await viewModel.rejectInvite(invite: invite) }
                                        }) {
                                            Text("Decline").bold().padding(.horizontal, 12).padding(.vertical, 6)
                                                .background(Color.red.opacity(0.15)).foregroundColor(.red).cornerRadius(8)
                                        }.buttonStyle(PlainButtonStyle())
                                        
                                        Button(action: {
                                            Task { await viewModel.acceptInvite(invite: invite) }
                                        }) {
                                            Text("Accept").bold().padding(.horizontal, 12).padding(.vertical, 6)
                                                .background(Color.blue).foregroundColor(.white).cornerRadius(8)
                                        }.buttonStyle(PlainButtonStyle())
                                    }.padding(.vertical, 4)
                                }
                            }
                        }
                        
                        // MARK: - Homes Section
                        if !viewModel.houses.isEmpty {
                            Section(header: Text("My Homes")) {
                                ForEach(viewModel.houses) { house in
                                    NavigationLink(destination: RoomsView(house: house)) {
                                        HStack(spacing: 14) {
                                            Text(flagForHouse(house.name))
                                                .font(.largeTitle)
                                                .frame(width: 36)
                                            
                                            VStack(alignment: .leading, spacing: 3) {
                                                Text(house.name)
                                                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                                                Text("Smart Home")
                                                    .font(.caption)
                                                    .foregroundColor(.secondary)
                                            }
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
            }
        }
    }
}

#Preview {
    HouseView()
}
