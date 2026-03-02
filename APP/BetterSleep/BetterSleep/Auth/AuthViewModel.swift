import SwiftUI
import Combine
import Foundation
import Supabase

@MainActor
class AuthViewModel: ObservableObject {
    @Published var isAuthenticated = false
    @Published var errorMessage: String? = nil
    
    // Check if a user is already logged in when the app starts
    func checkSession() async {
        do {
            _ = try await supabase.auth.session
            isAuthenticated = true
        } catch {
            isAuthenticated = false
        }
    }
    
    func signUp(email: String, password: String) async {
        do {
            // Registers the user in the Supabase auth.users table
            _ = try await supabase.auth.signUp(email: email, password: password)
            isAuthenticated = true
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
    
    func signIn(email: String, password: String) async {
        do {
            // <--- Updated method name here to fix the AuthClient error
            _ = try await supabase.auth.signIn(email: email, password: password)
            isAuthenticated = true
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }
    
    func signOut() async {
        do {
            try await supabase.auth.signOut()
            isAuthenticated = false
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
