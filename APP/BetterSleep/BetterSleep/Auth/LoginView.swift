import SwiftUI

struct LoginView: View {
    @Environment(\.colorScheme) var colorScheme
    
    @ObservedObject var authVM: AuthViewModel
    @State private var email = ""
    @State private var password = ""
    
    var body: some View {
        VStack(spacing: 80) {
            Spacer()
            
            // MARK: - Header
            VStack(spacing: 8) {
                Text("BetterSleep")
                    .font(.system(size: 42, weight: .heavy, design: .rounded))
                    .foregroundColor(.primary)
                
                Text("Your smart home sleep companion")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }
            
            
            VStack(spacing: 32) {
                // MARK: - Input Fields
                VStack(spacing: 16) {
                    HStack(spacing: 8) {
                        Image(systemName: "envelope.fill")
                            .foregroundColor(.gray)
                        
                        TextField("Email address", text: $email)
                            .textInputAutocapitalization(.never)
                            .keyboardType(.emailAddress)
                    }
                    .padding()
                    .background(Color(.systemGray6))
                    .cornerRadius(32)
                    
                    HStack(spacing: 8) {
                        Image(systemName: "lock.fill")
                            .foregroundColor(.gray)
                        
                        SecureField("Password", text: $password)
                    }
                    .padding()
                    .background(Color(.systemGray6))
                    .cornerRadius(32)
                }
                
                // MARK: - Error Message
                if let errorMessage = authVM.errorMessage {
                    Text(errorMessage)
                        .foregroundColor(.red)
                        .font(.caption)
                        .multilineTextAlignment(.center)
                        .padding(.top, 4)
                }
                
                // MARK: - Action Buttons
                VStack(spacing: 16) {
                    Button(action: {
                        Task { await authVM.signIn(email: email, password: password) }
                    }) {
                        HStack {
                            Spacer()
                            
                            Text("Sign In")
                                .font(.headline)
                            
                            Spacer()
                        }
                        .padding()
                    }
                    .frame(maxWidth: .infinity)
                    .buttonStyle(.glassProminent)
                    
                    
                    HStack(spacing: 4) {
                        Text("Don't have an account?")
                            .foregroundColor(.secondary)
                        
                        Button(action: {
                            Task { await authVM.signUp(email: email, password: password) }
                        }) {
                            Text("Sign Up")
                                .fontWeight(.semibold)
                                .foregroundColor(.blue)
                        }
                    }
                    .font(.footnote)
                }
            }
            
            Spacer()
        }
        .padding(.horizontal, 24)
    }
}

#Preview {
    LoginView(authVM: AuthViewModel())
}
