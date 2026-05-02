import Foundation
import SwiftUI
import Combine

@MainActor
class ProfileModel: ObservableObject {
    @Published var bedtime: Date = Calendar.current.date(bySettingHour: 22, minute: 0, second: 0, of: Date()) ?? Date()
    @Published var wakeTime: Date = Calendar.current.date(bySettingHour: 7, minute: 0, second: 0, of: Date()) ?? Date()
    @Published var serverHost: String = ""
    
    @Published var isLoading = true
    @Published var isSaving = false
    
    @Published var userEmail: String = ""
    private var currentUserId: Int?
    
    private var saveTask: Task<Void, Never>?
    private var serverHostSaveTask: Task<Void, Never>?
    
    private func baseURL() async throws -> String {
        try await CatalogClient.shared.getUserServiceURL()
    }
    
    private var timeFormatter: DateFormatter {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"
        return formatter
    }
    
    init() {
        if let idString = UserDefaults.standard.string(forKey: "currentUserId"), let id = Int(idString) {
            self.currentUserId = id
        }
        if let cachedEmail = UserDefaults.standard.string(forKey: "currentUserEmail") {
            self.userEmail = cachedEmail
        }
        if let savedHost = UserDefaults.standard.string(forKey: CatalogClient.manualPublicHostKey) {
            self.serverHost = savedHost
        }
    }
    
    func fetchPreferences() async {
        isLoading = true
        guard let userId = currentUserId else {
            isLoading = false
            return
        }
        
        do {
            let base = try await baseURL()
            let url = URL(string: "\(base)/getAllUsers")!
            let (data, _) = try await URLSession.shared.data(from: url)
            
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
                try await Task.sleep(nanoseconds: 1_000_000_000)
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
            let base = try await baseURL()
            var request = URLRequest(url: URL(string: "\(base)/updateUser")!)
            request.httpMethod = "PUT"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            
            let payload: [String: Any] = [
                "id": userId,
                "email": userEmail,
                "night_time": timeFormatter.string(from: bedtime),
                "morning_time": timeFormatter.string(from: wakeTime)
            ]
            
            request.httpBody = try JSONSerialization.data(withJSONObject: payload)
            _ = try await URLSession.shared.data(for: request)
        } catch {
            print("Error saving schedule: \(error)")
        }
        isSaving = false
    }

    func scheduleServerHostSave() {
        serverHostSaveTask?.cancel()
        serverHostSaveTask = Task {
            do {
                try await Task.sleep(nanoseconds: 500_000_000)
                await saveServerHost()
            } catch {
                // Task cancelled because the user is still typing.
            }
        }
    }

    func saveServerHost() async {
        let normalized = normalizeServerHost(serverHost)
        serverHost = normalized
        await CatalogClient.shared.setPublicHostOverride(normalized.isEmpty ? nil : normalized)
    }

    func applyScannedServerHost(_ scannedValue: String) async {
        let normalized = normalizeServerHost(scannedValue)
        guard !normalized.isEmpty else { return }
        serverHost = normalized
        await CatalogClient.shared.setPublicHostOverride(normalized)
    }

    private func normalizeServerHost(_ rawValue: String) -> String {
        let trimmed = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "" }

        if let components = URLComponents(string: trimmed), let host = components.host {
            return host
        }

        if let components = URLComponents(string: "http://\(trimmed)"), let host = components.host {
            return host
        }

        return trimmed
    }
}
