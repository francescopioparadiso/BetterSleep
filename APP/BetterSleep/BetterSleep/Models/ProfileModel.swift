import Foundation
import SwiftUI
import Combine

@MainActor
class ProfileModel: ObservableObject {
    // Defaults matching your init_catalog.sql
    @Published var bedtime: Date = Calendar.current.date(bySettingHour: 22, minute: 0, second: 0, of: Date()) ?? Date()
    @Published var wakeTime: Date = Calendar.current.date(bySettingHour: 7, minute: 0, second: 0, of: Date()) ?? Date()
    
    @Published var isLoading = true
    @Published var isSaving = false
    
    @Published var userEmail: String = ""
    private var currentUserId: Int?
    
    private var saveTask: Task<Void, Never>?
    private let baseURL = "http://127.0.0.1:9095"
    
    // Postgres stores these as text like "22:00", so we use HH:mm
    private var timeFormatter: DateFormatter {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }
    
    init() {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            self.currentUserId = id
        }
    }
    
    func fetchPreferences() async {
        isLoading = true
        guard let userId = currentUserId else {
            isLoading = false
            return
        }
        
        do {
            let url = URL(string: "\(baseURL)/getAllUsers")!
            let (data, _) = try await URLSession.shared.data(from: url)
            
            // Parse the JSON and find our specific user
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let usersList = json["users"] as? [[String: Any]],
               let currentUser = usersList.first(where: { ($0["id"] as? Int) == userId }) {
                
                self.userEmail = (currentUser["email"] as? String) ?? "Unknown Email"
                
                if let nightTimeStr = currentUser["night_time"] as? String,
                   let fetchedBedtime = timeFormatter.date(from: nightTimeStr) {
                    self.bedtime = fetchedBedtime
                }
                
                if let morningTimeStr = currentUser["morning_time"] as? String,
                   let fetchedWakeTime = timeFormatter.date(from: morningTimeStr) {
                    self.wakeTime = fetchedWakeTime
                }
            }
        } catch {
            print("Error fetching profile: \(error)")
        }
        isLoading = false
    }
    
    func triggerAutoSave() {
        guard !isLoading else { return }
        
        saveTask?.cancel()
        saveTask = Task {
            do {
                try await Task.sleep(nanoseconds: 1_000_000_000) // 1 second debounce
                await savePreferences()
            } catch {
                // Task cancelled because user is still adjusting the time
            }
        }
    }
    
    private func savePreferences() async {
        guard let userId = currentUserId else { return }
        isSaving = true
        
        do {
            var request = URLRequest(url: URL(string: "\(baseURL)/updateUser")!)
            request.httpMethod = "PUT"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            
            // Your Postgres update_user query requires id, email, night_time, and morning_time
            let payload: [String: Any] = [
                "id": userId,
                "email": userEmail,
                "night_time": timeFormatter.string(from: bedtime),
                "morning_time": timeFormatter.string(from: wakeTime)
            ]
            
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            _ = try await URLSession.shared.data(for: request)
            
            print("Global schedule saved successfully to Postgres!")
        } catch {
            print("Error saving schedule: \(error)")
        }
        isSaving = false
    }
}
