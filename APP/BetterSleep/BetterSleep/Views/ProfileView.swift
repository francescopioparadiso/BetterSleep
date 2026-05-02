import SwiftUI

struct ProfileView: View {
    @StateObject private var viewModel = ProfileModel()
    @State private var isShowingScanner = false
    // We pass AuthViewModel to handle signing out of the entire app
    @EnvironmentObject var authVM: AuthModel
    
    var body: some View {
        NavigationView {
            Form {
                if viewModel.isLoading {
                    Section {
                        HStack {
                            Spacer()
                            ProgressView("Loading profile...")
                            Spacer()
                        }
                    }
                    Section {
                        HStack(spacing: 12) {
                            TextField("192.168.1.88", text: $viewModel.serverHost)
                                .keyboardType(.numbersAndPunctuation)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .onSubmit {
                                    Task {
                                        await viewModel.saveServerHost()
                                    }
                                }

                            Button {
                                isShowingScanner = true
                            } label: {
                                Image(systemName: "qrcode.viewfinder")
                                    .font(.title3)
                            }
                            .accessibilityLabel("Scan QR code")
                        }
                    }
                } else {
                    // MARK: - Hero Header
                    Section {
                        VStack(spacing: 12) {
                            Image(systemName: "person.crop.circle.fill")
                                .font(.system(size: 80))
                                .foregroundColor(.blue)
                                .shadow(color: .blue, radius: 20, x: 0, y: 0)
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
                                .font(.title)
                                .frame(width: 40)
                                .foregroundColor(.indigo)
                                .shadow(color: .indigo.opacity(0.5), radius: 10, x: 0, y: 0)
                            DatePicker("Bedtime", selection: $viewModel.bedtime, displayedComponents: .hourAndMinute)
                        }
                        .padding(.vertical, 6)
                        
                        HStack {
                            Image(systemName: "sun.max.fill")
                                .font(.title)
                                .frame(width: 40)
                                .foregroundColor(.orange)
                                .shadow(color: .orange.opacity(0.5), radius: 10, x: 0, y: 0)
                            DatePicker("Wake Up", selection: $viewModel.wakeTime, displayedComponents: .hourAndMinute)
                        }
                        .padding(.vertical, 6)
                    }

                    // MARK: - Account Actions
                    Section {
                        Button(role: .destructive, action: {
                            Task {
                                authVM.signOut()
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
            }
            // Trigger the auto-save whenever the user changes a time
            .onChange(of: viewModel.bedtime) { _,_ in viewModel.triggerAutoSave() }
            .onChange(of: viewModel.wakeTime) { _,_ in viewModel.triggerAutoSave() }
            .onChange(of: viewModel.serverHost) { _, _ in
                viewModel.scheduleServerHostSave()
            }
            .refreshable {
                await viewModel.fetchPreferences()
            }
            .navigationTitle("Profile")
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    if viewModel.isSaving {
                        ProgressView()
                    }
                }
            }
            .task {
                await viewModel.fetchPreferences()
            }
            .sheet(isPresented: $isShowingScanner) {
                QRScannerView { scannedCode in
                    Task {
                        await viewModel.applyScannedServerHost(scannedCode)
                        isShowingScanner = false
                    }
                }
                .ignoresSafeArea()
            }
        }
    }
}

#Preview {
    ProfileView()
}
