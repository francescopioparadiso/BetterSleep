import SwiftUI
import Combine

// MARK: - Sleep Metric Type

enum SleepMetricType: Hashable {
    case duration, interruptions, remSleep, deepSleep, hrv, rhr

    var icon: String {
        switch self {
        case .duration:      return "bed.double.fill"
        case .interruptions: return "moon.zzz.fill"
        case .remSleep:      return "waveform.path"
        case .deepSleep:     return "moon.fill"
        case .hrv:           return "bolt.heart.fill"
        case .rhr:           return "arrow.down.heart.fill"
        }
    }

    var iconColor: Color {
        switch self {
        case .duration:      return .blue
        case .interruptions: return .orange
        case .remSleep:      return .purple
        case .deepSleep:     return .indigo
        case .hrv:           return .red
        case .rhr:           return .red
        }
    }

    var title: String {
        switch self {
        case .duration:      return "Sleep Duration"
        case .interruptions: return "Interruptions"
        case .remSleep:      return "REM Sleep"
        case .deepSleep:     return "Deep Sleep"
        case .hrv:           return "HRV"
        case .rhr:           return "RHR"
        }
    }

    var subtitle: String {
        switch self {
        case .duration:      return "Total hours asleep"
        case .interruptions: return "Times you woke up"
        case .remSleep:      return "Percentage of night"
        case .deepSleep:     return "Percentage of night"
        case .hrv:           return "Heart rate variability"
        case .rhr:           return "Resting heart rate"
        }
    }

    var useStackedValueLayout: Bool {
        return self == .interruptions || self == .remSleep || self == .deepSleep
    }
}

// MARK: - Sleep Dashboard ViewModel

@MainActor
class ChartsModel: ObservableObject {
    @Published var isLoading      = false
    @Published var sleepScore:    Double = 0
    @Published var sleepDuration: Double = 0   // hours
    @Published var interruptions: Double = 0   // count
    @Published var remSleep:      Double = 0   // percentage
    @Published var deepSleep:     Double = 0   // percentage
    @Published var hrv:           Double = 0   // ms
    @Published var rhr:           Double = 0   // bpm
    @Published var hasActiveRoom  = true

    func load() async {
        guard let userIdStr = UserDefaults.standard.string(forKey: "currentUserId"),
              let userId = Int(userIdStr) else { return }

        isLoading = true
        defer { isLoading = false }

        do {
            let base = try await CatalogClient.shared.getUserServiceURL()
            let url  = URL(string: "\(base)/getActiveRoom?user_id=\(userId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

            guard let activeRoomData = json?["active_room"] as? [String: Any],
                  let _ = activeRoomData["id"] as? Int else {
                hasActiveRoom = false
                return
            }
            hasActiveRoom = true

            // Fetch latest sleep analytics from MongoDB (via TimeSeries adapter)
            let tsURL = try await CatalogClient.shared.getTimeSeriesURL()
            let analyticsURL = URL(string: "\(tsURL)/getLatestSleepAnalytics?user_id=\(userId)")!
            let (analyticsData, _) = try await URLSession.shared.data(from: analyticsURL)
            let analytics = try JSONSerialization.jsonObject(with: analyticsData) as? [String: Any]

            // Check if we got an error or null response
            if let error = analytics?["error"] as? String {
                print("No sleep analytics found: \(error)")
                resetToDefaults()
                return
            }

            // Parse the MongoDB document
            if let analytics = analytics {
                sleepScore     = analytics["sleep_score"] as? Double ?? 0
                
                // Convert minutes to hours for sleepDuration
                let durationMin = analytics["sleep_duration_min"] as? Int ?? 0
                sleepDuration   = Double(durationMin) / 60.0
                
                interruptions  = Double(analytics["interruptions"] as? Int ?? 0)
                
                // REM and Deep are stored as minutes, but displayed as percentages
                let remMin = Double(analytics["rem_sleep_min"] as? Int ?? 0)
                let deepMin = Double(analytics["deep_sleep_min"] as? Int ?? 0)
                
                // Calculate percentages (assuming total sleep duration)
                if durationMin > 0 {
                    remSleep  = (remMin / Double(durationMin)) * 100.0
                    deepSleep = (deepMin / Double(durationMin)) * 100.0
                } else {
                    remSleep  = 0
                    deepSleep = 0
                }
                
                hrv = analytics["hrv_ms"] as? Double ?? 0
                rhr = analytics["rhr_bpm"] as? Double ?? 0
            } else {
                resetToDefaults()
            }
        } catch {
            print("SleepDashboard error: \(error)")
            resetToDefaults()
        }
    }

    private func resetToDefaults() {
        sleepScore    = 0
        sleepDuration = 0
        interruptions = 0
        remSleep      = 0
        deepSleep     = 0
        hrv           = 0
        rhr           = 0
    }

    // MARK: - Computed labels

    var sleepQualityLabel: String {
        switch sleepScore {
        case 80...:    return "Excellent"
        case 60..<80:  return "Good"
        case 40..<60:  return "Fair"
        default:       return "Poor"
        }
    }

    var sleepQualityColor: Color {
        switch sleepScore {
        case 80...:   return Color(red: 0.2,  green: 0.85, blue: 0.4)
        case 60..<80: return Color(red: 0.3,  green: 0.7,  blue: 1.0)
        case 40..<60: return Color(red: 1.0,  green: 0.7,  blue: 0.2)
        default:      return Color(red: 1.0,  green: 0.35, blue: 0.35)
        }
    }
}
