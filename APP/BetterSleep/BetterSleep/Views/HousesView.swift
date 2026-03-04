import SwiftUI

struct HouseView: View {
    @StateObject private var viewModel = HouseModel()
    
    @State private var showingAddHouse = false
    @State private var newHouseName = ""
    @State private var showingProfile = false // 🟢 Added this back!
    
    var body: some View {
        // 🟢 Added the NavigationView wrapper back!
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
                                    // Make sure you uncomment your NavigationLink when RoomsListView is ready!
                                    // NavigationLink(destination: RoomsListView(house: house)) {
                                    //     ...
                                    // }
                                    Text(house.name).font(.system(size: 18, weight: .medium, design: .rounded))
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
                // 🟢 Profile Button (Top Left)
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(action: { showingProfile = true }) {
                        Image(systemName: "person.fill")
                            .font(.title3)
                            .foregroundColor(.primary)
                    }
                }
                
                // 🟢 Add House Button (Top Right)
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
            // 🟢 Attach the Profile sheet here
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
