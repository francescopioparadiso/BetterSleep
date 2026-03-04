//import SwiftUI
//
//struct ManageInvitesView: View {
//    var houseId: Int // Changed from UUID to Int!
//    @StateObject private var houseVM = HouseViewModel()
//    @Environment(\.dismiss) var dismiss
//    
//    @State private var emailToInvite = ""
//    @State private var isSending = false
//    @State private var errorMessage: String? = nil
//    @State private var isFetching = true
//    
//    // Check if current user is owner (role == 0 in Postgres)
//    var isCurrentUserOwner: Bool {
//        houseVM.currentHouseMembers.first(where: { $0.user_id == houseVM.currentUserId })?.role == 0
//    }
//    
//    // Sort members so the Owner always appears at the top
//    var sortedMembers: [HouseMember] {
//        houseVM.currentHouseMembers.sorted { a, b in
//            if a.role == 0 { return true }
//            if b.role == 0 { return false }
//            return (a.email ?? "") < (b.email ?? "")
//        }
//    }
//    
//    var body: some View {
//        NavigationView {
//            List {
//                Section(header: Text("House Access"), footer: Text("Users must create a BetterSleep account before they can be invited.")) {
//                    if isFetching {
//                        HStack {
//                            Spacer()
//                            ProgressView("Loading access list...")
//                            Spacer()
//                        }.listRowBackground(Color.clear).padding(.vertical, 12)
//                    } else {
//                        // --- 1. ACTIVE MEMBERS ---
//                        ForEach(sortedMembers) { member in
//                            HStack {
//                                Image(systemName: member.role == 0 ? "star.fill" : "person.fill")
//                                    .foregroundColor(member.role == 0 ? .yellow : .blue).frame(width: 30)
//                                
//                                VStack(alignment: .leading) {
//                                    Text(member.email ?? "Unknown User").font(.body)
//                                    Text(member.user_id == houseVM.currentUserId ? "You" : "Housemate")
//                                        .font(.caption).foregroundColor(.secondary)
//                                }
//                                Spacer()
//                                
//                                Text(member.role == 0 ? "Owner" : "Guest")
//                                    .font(.caption).bold()
//                                    .padding(.horizontal, 8).padding(.vertical, 4)
//                                    .background(member.role == 0 ? Color.yellow.opacity(0.2) : Color.gray.opacity(0.2))
//                                    .foregroundColor(member.role == 0 ? .yellow : .primary).cornerRadius(8)
//                            }
//                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
//                                if isCurrentUserOwner && member.user_id != houseVM.currentUserId {
//                                    Button(role: .destructive) {
//                                        Task { if let id = member.id { await houseVM.removeMember(memberId: id) } }
//                                    } label: { Label("Remove", systemImage: "trash") }
//                                }
//                            }
//                        }
//                        
//                        // --- 2. PENDING INVITES (status == 0) ---
//                        let pendingInvites = houseVM.currentHouseInvites.filter { $0.status == 0 }
//                        ForEach(pendingInvites) { invite in
//                            HStack {
//                                Image(systemName: "questionmark.circle.fill").foregroundColor(.orange).frame(width: 30)
//                                Text(invite.email).foregroundColor(.primary)
//                                Spacer()
//                                Text("Pending").font(.caption).bold()
//                                    .padding(.horizontal, 8).padding(.vertical, 4)
//                                    .background(Color.orange.opacity(0.2)).foregroundColor(.orange).cornerRadius(8)
//                            }
//                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
//                                if isCurrentUserOwner {
//                                    Button(role: .destructive) {
//                                        Task {
//                                            if let id = invite.id {
//                                                await houseVM.deleteInvite(inviteId: id)
//                                                await houseVM.fetchHouseDetails(for: houseId)
//                                            }
//                                        }
//                                    } label: { Label("Cancel", systemImage: "xmark.circle") }
//                                }
//                            }
//                        }
//                        
//                        // --- 3. ADDING ROW ---
//                        VStack(alignment: .leading, spacing: 0) {
//                            HStack {
//                                Image(systemName: "envelope.badge.fill").foregroundColor(.blue).frame(width: 30)
//                                TextField("Invite housemate via email...", text: $emailToInvite)
//                                    .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
//                                
//                                if isSending { ProgressView() } else {
//                                    Button(action: sendInvite) {
//                                        Image(systemName: "paperplane.fill").font(.system(size: 18, weight: .bold))
//                                            .foregroundColor(emailToInvite.isEmpty || !emailToInvite.contains("@") ? .gray : .blue)
//                                    }.disabled(emailToInvite.isEmpty || !emailToInvite.contains("@")).buttonStyle(PlainButtonStyle())
//                                }
//                            }
//                            if let error = errorMessage { Text(error).font(.caption).foregroundColor(.red).padding(.top, 4).padding(.leading, 38) }
//                        }.padding(.vertical, 4)
//                    }
//                }
//            }
//            .listStyle(.insetGrouped)
//            .navigationTitle("Manage Access")
//            .navigationBarTitleDisplayMode(.inline)
//            .toolbar { ToolbarItem(placement: .navigationBarTrailing) { Button("Done") { dismiss() } } }
//            .task {
//                isFetching = true
//                await houseVM.fetchHouseDetails(for: houseId)
//                isFetching = false
//            }
//        }
//    }
//    
//    private func sendInvite() {
//        Task {
//            isSending = true
//            errorMessage = nil
//            let userExists = await houseVM.checkUserExists(email: emailToInvite.lowercased())
//            if userExists {
//                await houseVM.inviteUser(email: emailToInvite, to: houseId)
//                emailToInvite = ""
//                await houseVM.fetchHouseDetails(for: houseId)
//            } else { errorMessage = "User not found. They must sign up first." }
//            isSending = false
//        }
//    }
//}
