import Foundation
import SwiftUI
import Combine
import Supabase

@MainActor
class ProfileViewModel: ObservableObject {
    @Published var bedtime: Date = Calendar.current.date(bySettingHour: 22, minute: 30, second: 0, of: Date()) ?? Date()
    @Published var wakeTime: Date = Calendar.current.date(bySettingHour: 7, minute: 0, second: 0, of: Date()) ?? Date()
    
    @Published var isLoading = true
    @Published var isSaving = false
    
    @Published var userEmail: String = ""
    
    private var hasExistingRecord = false
    private var saveTask: Task<Void, Never>?
    
    private var timeFormatter: DateFormatter {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }
    
    func fetchPreferences() async {
        isLoading = true
        do {
            let session = try await supabase.auth.session
            let userId = session.user.id
            
            self.userEmail = session.user.email ?? "Unknown Email"
            
            // Fetch global preferences for this specific user
            let response: [GlobalPreferences] = try await supabase
                .from("global_preferences")
                .select()
                .eq("user_id", value: userId)
                .execute()
                .value
            
            if let savedPrefs = response.first {
                self.hasExistingRecord = true
                if let fetchedBedtime = timeFormatter.date(from: savedPrefs.bedtime) {
                    self.bedtime = fetchedBedtime
                }
                if let fetchedWakeTime = timeFormatter.date(from: savedPrefs.wake_time) {
                    self.wakeTime = fetchedWakeTime
                }
            }
        } catch {
            print("No existing global preferences found. Using defaults.")
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
        isSaving = true
        do {
            let session = try await supabase.auth.session
            let userId = session.user.id
            
            let newPreferences = GlobalPreferences(
                user_id: userId,
                bedtime: timeFormatter.string(from: bedtime),
                wake_time: timeFormatter.string(from: wakeTime)
            )
            
            if hasExistingRecord {
                try await supabase
                    .from("global_preferences")
                    .update(newPreferences)
                    .eq("user_id", value: userId)
                    .execute()
            } else {
                try await supabase
                    .from("global_preferences")
                    .insert(newPreferences)
                    .execute()
                self.hasExistingRecord = true
            }
            print("Global schedule saved successfully!")
        } catch {
            print("Error saving schedule: \(error)")
        }
        isSaving = false
    }
}

// Ensure this model is also in your DataModels.swift file or at the bottom here!
struct GlobalPreferences: Codable {
    var user_id: UUID?
    var bedtime: String
    var wake_time: String
}
