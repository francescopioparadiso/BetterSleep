import SwiftUI

struct ProfileView: View {
    @StateObject private var viewModel = ProfileModel()
    // We pass AuthViewModel to handle signing out of the entire app
    @EnvironmentObject var authVM: AuthModel
    @Environment(\.dismiss) var dismiss
    
    var body: some View {
        NavigationView {
            Group {
                if viewModel.isLoading {
                    ProgressView("Loading profile...")
                } else {
                    Form {
                        // MARK: - Hero Header
                        Section {
                            VStack(spacing: 12) {
                                Image(systemName: "person.crop.circle.fill")
                                    .font(.system(size: 80))
                                    .foregroundColor(.blue)
                                    .shadow(color: .blue, radius: 12, x: 0, y: 0)
                                    .padding(.top, 48)
                                
                                // Display the email, falling back to "Account Settings" if empty
                                Text(viewModel.userEmail.isEmpty ? "Account Settings" : viewModel.userEmail)
                                    .font(.title2)
                                    .fontWeight(.semibold)
                                    .fontDesign(.rounded)
                            }
                            .frame(maxWidth: .infinity)
                            .listRowBackground(Color.clear)
                        }
                        
                        // MARK: - Sleep Schedule Settings
                        Section(header: Text("Global Sleep Schedule")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                            .fontDesign(.rounded)) {
                            HStack {
                                Image(systemName: "moon.zzz.fill")
                                    .foregroundColor(.indigo)
                                    .frame(width: 30)
                                DatePicker("Bedtime", selection: $viewModel.bedtime, displayedComponents: .hourAndMinute)
                            }
                            .padding(.vertical, 6)
                            
                            HStack {
                                Image(systemName: "sun.max.fill")
                                    .foregroundColor(.orange)
                                    .frame(width: 30)
                                DatePicker("Wake Up", selection: $viewModel.wakeTime, displayedComponents: .hourAndMinute)
                            }
                            .padding(.vertical, 6)
                        }
                        
                        // MARK: - Account Actions
                        Section {
                            Button(role: .destructive, action: {
                                Task {
                                    await authVM.signOut()
                                    dismiss()
                                }
                            }) {
                                HStack {
                                    Spacer()
                                    Text("Sign Out")
                                        .fontWeight(.semibold)
                                    Spacer()
                                }
                            }
                        }
                    }
                    // Trigger the auto-save whenever the user changes a time
                    .onChange(of: viewModel.bedtime) { _,_ in viewModel.triggerAutoSave() }
                    .onChange(of: viewModel.wakeTime) { _,_ in viewModel.triggerAutoSave() }
                }
            }
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .navigationBarLeading) {
                    if viewModel.isSaving {
                        ProgressView()
                    }
                }
            }
            .task {
                await viewModel.fetchPreferences()
            }
        }
    }
}

#Preview {
    ProfileView()
}
