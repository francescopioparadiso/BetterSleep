import Foundation
import Combine

@MainActor
class AuthViewModel: ObservableObject {
    @Published var isAuthenticated = false
    @Published var errorMessage: String? = nil
    
    // TODO: Point this to your new Python User Management Microservice IP
    private let baseURL = "http://127.0.0.1:9095"
    
    // Check if a user is already logged in when the app starts
    func checkSession() {
        // Since we don't have Supabase managing tokens anymore,
        // we check local storage for a saved user ID.
        if UserDefaults.standard.string(forKey: "currentUserId") != nil {
            isAuthenticated = true
        } else {
            isAuthenticated = false
        }
    }
    
    func signUp(email: String, password: String) async {
        guard let url = URL(string: "\(baseURL)/signup") else { return }
        
        let payload = ["email": email, "password": password]
        
        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else { return }
            
            if httpResponse.statusCode == 200 || httpResponse.statusCode == 201 {
                // Parse the new user ID returned by your Postgres DB
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let userId = json["id"] {
                    UserDefaults.standard.set("\(userId)", forKey: "currentUserId")
                    self.isAuthenticated = true
                    self.errorMessage = nil
                }
            } else {
                self.errorMessage = "Sign up failed. Email might already be in use."
            }
        } catch {
            self.errorMessage = error.localizedDescription
        }
    }
    
    func signIn(email: String, password: String) async {
        guard let url = URL(string: "\(baseURL)/login") else { return }
        
        let payload = ["email": email, "password": password]
        
        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else { return }
            
            if httpResponse.statusCode == 200 {
                // Parse the user ID returned by your Postgres DB
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let userId = json["id"] {
                    UserDefaults.standard.set("\(userId)", forKey: "currentUserId")
                    self.isAuthenticated = true
                    self.errorMessage = nil
                }
            } else {
                self.errorMessage = "Invalid email or password."
            }
        } catch {
            self.errorMessage = "Network error: \(error.localizedDescription)"
        }
    }
    
    func signOut() {
        // Clear local storage to log out
        UserDefaults.standard.removeObject(forKey: "currentUserId")
        self.isAuthenticated = false
    }
}
