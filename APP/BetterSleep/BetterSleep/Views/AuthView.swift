import SwiftUI

struct AuthView: View {
    @Environment(\.colorScheme) var colorScheme
    
    @ObservedObject var authVM: AuthModel
    @State private var email = ""
    @State private var password = ""
    
    @State private var toastAnimation = Animation.bouncy(duration: 0.5)
    
    var body: some View {
        ZStack(alignment: .top) {
            
            // MARK: - Main Content
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
                                .frame(width: 24)
                            
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
                                .frame(width: 24)
                            
                            SecureField("Password", text: $password)
                        }
                        .padding()
                        .background(Color(.systemGray6))
                        .cornerRadius(32)
                    }
                    
                    // MARK: - Action Buttons
                    VStack(spacing: 16) {
                        Button(action: {
                            Task {
                                // Clear old errors so the animation can re-trigger if needed
                                withAnimation { authVM.errorMessage = nil }
                                await authVM.signIn(email: email, password: password)
                            }
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
                                Task {
                                    withAnimation { authVM.errorMessage = nil }
                                    await authVM.signUp(email: email, password: password)
                                }
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
            .padding(.horizontal)
            
            // MARK: - Dynamic Island Error Toast
            if let errorMessage = authVM.errorMessage {
                HStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    
                    Text(errorMessage)
                        .font(.subheadline.weight(.medium))
                        .lineLimit(2)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .foregroundStyle(Color.red)
                .background(Color.red.opacity(0.15))
                .clipShape(.rect(cornerRadius: 24))
                .shadow(color: Color.red, radius: 30, x: 0, y: 0)
                
                .transition(.asymmetric(
                    insertion: .move(edge: .top).combined(with: .opacity).combined(with: .scale(scale: 0.5)),
                    removal: .move(edge: .top).combined(with: .opacity).combined(with: .scale(scale: 0.5))
                ))
                .zIndex(1)
                .onAppear {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3.5) {
                        withAnimation(toastAnimation) {
                            authVM.errorMessage = nil
                        }
                    }
                }
            }
        }
        .animation(toastAnimation, value: authVM.errorMessage)
    }
}

#Preview {
    // 🟢 Fixed the Model name here!
    AuthView(authVM: AuthModel())
}
