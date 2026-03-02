import SwiftUI
import Combine
import Foundation
import Supabase

struct HousesListView: View {
    @StateObject private var viewModel = HouseViewModel()
    
    @State private var showingAddHouse = false
    @State private var newHouseName = ""
    @State private var showingProfile = false
    
    var body: some View {
        NavigationView {
            Group {
                if viewModel.isLoading {
                    ProgressView("Loading your homes...")
                } else if viewModel.houses.isEmpty && viewModel.pendingInvites.isEmpty {
                    // MARK: - Empty State
                    ContentUnavailableView(
                        "No Homes Found",
                        systemImage: "house.circle",
                        description: Text("Tap the + button in the top right to create your first smart home.")
                    )
                } else {
                    List {
                        // MARK: - Pending Invites Section
                        if !viewModel.pendingInvites.isEmpty {
                            Section(header: Text("Pending Invitations").foregroundColor(.blue)) {
                                ForEach(viewModel.pendingInvites) { invite in
                                    HStack {
                                        VStack(alignment: .leading) {
                                            Text("Home Invitation")
                                                .font(.headline)
                                            Text("Tap accept to join this home.")
                                                .font(.caption)
                                                .foregroundColor(.secondary)
                                        }
                                        Spacer()
                                        
                                        // DECLINE BUTTON
                                        Button(action: {
                                            Task { await viewModel.rejectInvite(invite: invite) }
                                        }) {
                                            Text("Decline")
                                                .bold()
                                                .padding(.horizontal, 12)
                                                .padding(.vertical, 6)
                                                .background(Color.red.opacity(0.15))
                                                .foregroundColor(.red)
                                                .cornerRadius(8)
                                        }
                                        .buttonStyle(PlainButtonStyle())
                                        
                                        // ACCEPT BUTTON
                                        Button(action: {
                                            Task { await viewModel.acceptInvite(invite: invite) }
                                        }) {
                                            Text("Accept")
                                                .bold()
                                                .padding(.horizontal, 12)
                                                .padding(.vertical, 6)
                                                .background(Color.blue)
                                                .foregroundColor(.white)
                                                .cornerRadius(8)
                                        }
                                        .buttonStyle(PlainButtonStyle())
                                    }
                                    .padding(.vertical, 4)
                                }
                            }
                        }
                        
                        // MARK: - Homes Section
                        if !viewModel.houses.isEmpty {
                            Section(header: Text("My Homes")) {
                                ForEach(viewModel.houses) { house in
                                    NavigationLink(destination: RoomsListView(house: house)) {
                                        HStack(spacing: 16) {
                                            Image(systemName: "house.fill")
                                                .font(.title2)
                                                .foregroundColor(.blue)
                                                .frame(width: 40, height: 40)
                                                .background(Color.blue.opacity(0.15))
                                                .cornerRadius(10)
                                            
                                            Text(house.name)
                                                .font(.system(size: 18, weight: .medium, design: .rounded))
                                        }
                                        .padding(.vertical, 8)
                                    }
                                }
                                // Swipe-to-delete modifier for houses
                                .onDelete { indexSet in
                                    Task { await viewModel.deleteHouse(at: indexSet) }
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("BetterSleep")
            .toolbar {
                // Profile Button
                ToolbarItem(placement: .navigationBarLeading) {
                    Button(action: { showingProfile = true }) {
                        Image(systemName: "person.crop.circle.fill")
                            .font(.title3)
                            .foregroundColor(.blue)
                    }
                }
                // Add House Button
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: { showingAddHouse = true }) {
                        Image(systemName: "plus.circle.fill")
                            .font(.title3)
                            .foregroundColor(.blue)
                    }
                }
            }
            .alert("Create a Home", isPresented: $showingAddHouse) {
                TextField("Home Name (e.g. My Apartment)", text: $newHouseName)
                Button("Cancel", role: .cancel) { newHouseName = "" }
                Button("Create") {
                    Task {
                        await viewModel.addHouse(name: newHouseName)
                        newHouseName = ""
                    }
                }
            }
            .sheet(isPresented: $showingProfile) {
                ProfileView()
            }
            .task {
                // Fetch both houses and invites when the view loads
                await viewModel.fetchHouses()
                await viewModel.fetchPendingInvites()
            }
        }
    }
}

#Preview {
    HousesListView()
}
