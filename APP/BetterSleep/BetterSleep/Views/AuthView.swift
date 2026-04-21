import SwiftUI

// MARK: - Support Types
enum AuthField: Hashable {
    case email
    case password
}

enum AuthStatus: Equatable {
    case idle
    case loading
    case success
    case error(String)
    
    var value: Double {
        switch self {
        case .idle: return 0
        case .loading: return 1
        case .success: return 2
        case .error: return 3
        }
    }
    
    func tint(isInputValid: Bool) -> Color {
        if !isInputValid && self == .idle {
            return .blue.opacity(0.1)
        }
        switch self {
        case .error: return .red.opacity(0.2)
        case .success: return .green.opacity(0.2)
        default: return .blue.opacity(0.2)
        }
    }
    
    func foreground(isInputValid: Bool) -> Color {
        if !isInputValid && self == .idle {
            return .blue.opacity(0.5)
        }
        switch self {
        case .error: return .red
        case .success: return .green
        default: return .blue
        }
    }
}

struct AuthView: View {
    @Environment(\.colorScheme) var colorScheme
    
    @ObservedObject var authVM: AuthModel
    @State private var email = ""
    @State private var password = ""
    
    // MARK: - Focus Management
    @FocusState private var focusedField: AuthField?
    
    @State private var toastAnimation = Animation.bouncy(duration: 0.5)
    
    @State private var signInStatus: AuthStatus = .idle
    @State private var signUpStatus: AuthStatus = .idle
    
    private var isInputValid: Bool {
        !email.isEmpty && !password.isEmpty
    }
    
    var body: some View {
        ZStack {    
            // MARK: - Main Content
            VStack(spacing: focusedField != nil ? 20 : 80) {
                Spacer()
                
                if focusedField == nil {
                    // MARK: - Header
                    VStack(spacing: 8) {
                        Image("bettersleep-logo")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 60, height: 60)
                            .shadow(color: Color.blue.opacity(0.9), radius: 60, x: 0, y: 0)
                        
                        Text("BetterSleep")
                            .font(.largeTitle)
                            .fontWeight(.heavy)
                            .fontDesign(.rounded)
                            .foregroundColor(.primary)
                        
                        Text("Your smart home sleep companion")
                            .font(.subheadline)
                            .fontDesign(.rounded)
                            .foregroundColor(.secondary)
                    }
                    .transition(.move(edge: .top).combined(with: .opacity))
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
                                .focused($focusedField, equals: .email)
                                .submitLabel(.next)
                        }
                        .padding()
                        .background(Color(.systemGray6))
                        .cornerRadius(32)
                        
                        HStack(spacing: 8) {
                            Image(systemName: "lock.fill")
                                .foregroundColor(.gray)
                                .frame(width: 24)
                            
                            SecureField("Password", text: $password)
                                .textInputAutocapitalization(.never)
                                .keyboardType(.emailAddress)
                                .focused($focusedField, equals: .password)
                                .submitLabel(.next)
                        }
                        .padding()
                        .background(Color(.systemGray6))
                        .cornerRadius(32)
                    }
                    .onSubmit {
                        if focusedField == .email {
                            focusedField = .password
                        } else {
                            focusedField = nil
                        }
                    }
                    
                    // MARK: - Action Buttons
                    VStack(spacing: 16) {
                        Button(action: {
                            focusedField = nil
                            Task {
                                withAnimation { signInStatus = .loading }
                                try? await Task.sleep(nanoseconds: 2_000_000_000)
                                
                                await authVM.signIn(email: email, password: password)
                                
                                if let error = authVM.errorMessage {
                                    withAnimation { signInStatus = .error(error) }
                                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                                    withAnimation { signInStatus = .idle }
                                } else {
                                    withAnimation { signInStatus = .success }
                                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                                    authVM.isAuthenticated = true
                                }
                            }
                        }) {
                            HStack {
                                Spacer()

                                var textString: String {
                                    switch signInStatus {
                                    case .idle: return "Sign In"
                                    case .loading: return "Logging in..."
                                    case .success: return "Successful"
                                    case .error(let msg): return msg
                                    }
                                }

                                Text(textString)
                                    .font(.headline)
                                    .fontDesign(.rounded)
                                    .contentTransition(.numericText(value: Double(textString.hashValue)))

                                Spacer()
                            }
                            .padding()
                        }
                        .frame(maxWidth: .infinity)
                        .buttonStyle(.glassProminent)
                        .tint(signInStatus.tint(isInputValid: isInputValid))
                        .foregroundStyle(signInStatus.foreground(isInputValid: isInputValid))
                        .disabled(signInStatus != .idle || signUpStatus != .idle || !isInputValid)
                        
                        HStack(spacing: 4) {
                            Text("Don't have an account?")
                                .fontDesign(.rounded)
                                .foregroundColor(.secondary)
                            
                            Button(action: {
                                focusedField = nil
                                Task {
                                    withAnimation { signUpStatus = .loading }
                                    try? await Task.sleep(nanoseconds: 2_000_000_000)
                                    
                                    await authVM.signUp(email: email, password: password)
                                    
                                    if let error = authVM.errorMessage {
                                        withAnimation { signUpStatus = .error(error) }
                                        try? await Task.sleep(nanoseconds: 2_000_000_000)
                                        withAnimation { signUpStatus = .idle }
                                    } else {
                                        withAnimation { signUpStatus = .success }
                                        try? await Task.sleep(nanoseconds: 2_000_000_000)
                                        authVM.isAuthenticated = true
                                    }
                                }
                            }) {
                                Group {
                                    switch signUpStatus {
                                    case .idle:
                                        Text("Sign Up")
                                    case .loading:
                                        Text("Signing up...")
                                    case .success:
                                        Text("Successful")
                                    case .error(let msg):
                                        Text(msg)
                                    }
                                }
                                .fontWeight(.semibold)
                                .fontDesign(.rounded)
                                .foregroundColor(signUpStatus.foreground(isInputValid: isInputValid))
                                .contentTransition(.numericText(value: Double(signUpStatus.value)))
                            }
                            .disabled(signInStatus != .idle || signUpStatus != .idle || !isInputValid)
                        }
                        .font(.footnote)
                    }
                }
                
                Spacer()
            }
            .padding(.horizontal)
            .animation(.snappy, value: focusedField)
        }
        .animation(toastAnimation, value: authVM.errorMessage)
    }
}

#Preview("Normal State") {
    AuthView(authVM: AuthModel())
}

#Preview("Error State") {
    let vm = AuthModel()
    vm.errorMessage = "Invalid email or password."
    return AuthView(authVM: vm)
}
