import SwiftUI
import Supabase

struct ManageInvitesView: View {
    var houseId: UUID
    @StateObject private var houseVM = HouseViewModel()
    @Environment(\.dismiss) var dismiss
    
    @State private var emailToInvite = ""
    @State private var isSending = false
    @State private var errorMessage: String? = nil
    @State private var isFetching = true // Controls the initial loading spinner
    
    // Check if the current user is the owner to allow deleting guests
    var isCurrentUserOwner: Bool {
        houseVM.currentHouseMembers.first(where: { $0.user_id == houseVM.currentUserId })?.role == "owner"
    }
    
    // Sort members so the Owner always appears at the very top of the list
    var sortedMembers: [HouseMember] {
        houseVM.currentHouseMembers.sorted { a, b in
            if a.role == "owner" { return true }
            if b.role == "owner" { return false }
            return a.email < b.email
        }
    }
    
    var body: some View {
        NavigationView {
            List {
                // MARK: - Unified Access List
                Section(
                    header: Text("House Access"),
                    footer: Text("Users must create a BetterSleep account before they can be invited.")
                ) {
                    if isFetching {
                        // Show a spinner centered in the list while fetching
                        HStack {
                            Spacer()
                            ProgressView("Loading access list...")
                            Spacer()
                        }
                        .listRowBackground(Color.clear)
                        .padding(.vertical, 12)
                        
                    } else {
                        // --- 1. ACTIVE MEMBERS (Owner First, then Guests) ---
                        ForEach(sortedMembers) { member in
                            HStack {
                                // Leading Icon
                                Image(systemName: member.role == "owner" ? "star.fill" : "person.fill")
                                    .foregroundColor(member.role == "owner" ? .yellow : .blue)
                                    .frame(width: 30)
                                
                                VStack(alignment: .leading) {
                                    Text(member.email).font(.body)
                                    Text(member.user_id == houseVM.currentUserId ? "You" : "Housemate")
                                        .font(.caption).foregroundColor(.secondary)
                                }
                                Spacer()
                                
                                // Proper Label for Owner vs Guest
                                Text(member.role == "owner" ? "Owner" : "Guest")
                                    .font(.caption).bold()
                                    .padding(.horizontal, 8).padding(.vertical, 4)
                                    .background(member.role == "owner" ? Color.yellow.opacity(0.2) : Color.gray.opacity(0.2))
                                    .foregroundColor(member.role == "owner" ? .yellow : .primary)
                                    .cornerRadius(8)
                            }
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                if isCurrentUserOwner && member.user_id != houseVM.currentUserId {
                                    Button(role: .destructive) {
                                        Task {
                                            // Safely unwrap the optional ID
                                            if let memberId = member.id {
                                                await houseVM.removeMember(memberId: memberId)
                                            }
                                        }
                                    } label: {
                                        Label("Remove", systemImage: "trash")
                                    }
                                }
                            }
                        }
                        
                        // --- 2. PENDING INVITES ---
                        let pendingInvites = houseVM.currentHouseInvites.filter { $0.status == "pending" }
                        ForEach(pendingInvites) { invite in
                            HStack {
                                // Leading Icon with Orange Question Mark
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
                            // Optional: Swipe to cancel/delete a pending invite
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                if isCurrentUserOwner {
                                    Button(role: .destructive) {
                                        Task {
                                            if let inviteId = invite.id {
                                                _ = try? await supabase.from("invitations").delete().eq("id", value: inviteId).execute()
                                                await houseVM.fetchHouseDetails(for: houseId)
                                            }
                                        }
                                    } label: {
                                        Label("Cancel", systemImage: "xmark.circle")
                                    }
                                }
                            }
                        }
                        
                        // --- 3. THE ADDING ROW (Bottom of the list) ---
                        VStack(alignment: .leading, spacing: 0) {
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
                                        Image(systemName: "paperplane.fill")
                                            .font(.system(size: 18, weight: .bold))
                                            .foregroundColor(emailToInvite.isEmpty || !emailToInvite.contains("@") ? .gray : .blue)
                                    }
                                    .disabled(emailToInvite.isEmpty || !emailToInvite.contains("@"))
                                    .buttonStyle(PlainButtonStyle()) // Prevents the whole row from becoming clickable
                                }
                            }
                            
                            // Display error messages right below the text field
                            if let error = errorMessage {
                                Text(error)
                                    .font(.caption)
                                    .foregroundColor(.red)
                                    .padding(.top, 4)
                                    .padding(.leading, 38) // Aligns with the text field (past the icon)
                            }
                        }
                        .padding(.vertical, 4)
                        
                    }
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Manage Access")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .task {
                isFetching = true
                await houseVM.fetchHouseDetails(for: houseId)
                isFetching = false
            }
        }
    }
    
    // MARK: - Actions
    private func sendInvite() {
        Task {
            isSending = true
            errorMessage = nil
            
            // 1. Check if user exists
            let userExists = await houseVM.checkUserExists(email: emailToInvite.lowercased())
            
            if userExists {
                // 2. Send the invite
                await houseVM.inviteUser(email: emailToInvite, to: houseId)
                emailToInvite = ""
                // 3. Refresh lists
                await houseVM.fetchHouseDetails(for: houseId)
            } else {
                errorMessage = "User not found. They must sign up first."
            }
            isSending = false
        }
    }
}
