import Foundation
import Combine

@MainActor
class AuthModel: ObservableObject {
    @Published var isAuthenticated = false
    @Published var errorMessage: String? = nil
    
    private func baseURL() async throws -> String {
        try await CatalogClient.shared.getUserServiceURL()
    }
    
    func checkSession() {
        if UserDefaults.standard.string(forKey: "currentUserId") != nil {
            isAuthenticated = true
        } else {
            isAuthenticated = false
        }
    }
    
    func signUp(email: String, password: String) async {
        guard let base = try? await baseURL(),
              let url = URL(string: "\(base)/signup") else {
            self.errorMessage = "Unable to reach the service catalog."
            return
        }
        
        let payload = ["email": email, "password": password]
        
        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else { return }
            
            if httpResponse.statusCode == 200 || httpResponse.statusCode == 201 {
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let userId = json["id"] {
                    UserDefaults.standard.set("\(userId)", forKey: "currentUserId")
                    UserDefaults.standard.set(email, forKey: "currentUserEmail")
                    
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
        guard let base = try? await baseURL(),
              let url = URL(string: "\(base)/login") else {
            self.errorMessage = "Unable to reach the service catalog."
            return
        }
        
        let payload = ["email": email, "password": password]
        
        do {
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else { return }
            
            if httpResponse.statusCode == 200 {
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let userId = json["id"] {
                    UserDefaults.standard.set("\(userId)", forKey: "currentUserId")
                    UserDefaults.standard.set(email, forKey: "currentUserEmail")
                    
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
        UserDefaults.standard.removeObject(forKey: "currentUserId")
        UserDefaults.standard.removeObject(forKey: "currentUserEmail")
        self.isAuthenticated = false
    }
}
