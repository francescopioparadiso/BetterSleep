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
    @Published var isRefreshing   = false
    @Published var sleepScore:    Double = 0
    @Published var sleepDuration: Double = 0   // hours
    @Published var interruptions: Double = 0   // count
    @Published var remSleep:      Double = 0   // percentage
    @Published var deepSleep:     Double = 0   // percentage
    
    // Stage durations (minutes)
    @Published var awakeMinutes:  Double = 0
    @Published var lightMinutes:  Double = 0
    @Published var deepMinutes:   Double = 0
    @Published var remMinutes:    Double = 0

    @Published var hrv:           Double = 0   // ms
    @Published var rhr:           Double = 0   // bpm
    @Published var hasActiveRoom  = true
    @Published var hasData        = false
    @Published var selectedDate   = Date()

    private var latestLoadID = UUID()
    private var hasCompletedFirstLoad = false

    // MARK: - Navigation title

    var navigationTitle: String {
        let calendar = Calendar.current
        let formatter = DateFormatter()

        if calendar.isDateInToday(selectedDate) {
            formatter.dateFormat = "MMM d"
            return "Today, \(formatter.string(from: selectedDate))"
        } else if calendar.isDateInYesterday(selectedDate) {
            formatter.dateFormat = "MMM d"
            return "Yesterday, \(formatter.string(from: selectedDate))"
        } else {
            // Check if same year
            if calendar.component(.year, from: selectedDate) == calendar.component(.year, from: Date()) {
                formatter.dateFormat = "MMM d"
            } else {
                formatter.dateFormat = "MMM d, yyyy"
            }
            return formatter.string(from: selectedDate)
        }
    }

    // MARK: - Load by date

    var shouldShowBlockingLoader: Bool {
        isLoading && !hasCompletedFirstLoad
    }

    func load() async {
        await load(for: selectedDate)
    }

    func refresh() async {
        await load(for: selectedDate, preserveVisibleState: true)
    }

    func load(for date: Date, preserveVisibleState: Bool = false) async {
        guard let userIdStr = UserDefaults.standard.string(forKey: "currentUserId"),
              let userId = Int(userIdStr) else { return }

        let loadID = UUID()
        latestLoadID = loadID

        if preserveVisibleState || hasCompletedFirstLoad {
            isRefreshing = true
        } else {
            isLoading = true
        }
        defer {
            if latestLoadID == loadID {
                isLoading = false
                isRefreshing = false
                hasCompletedFirstLoad = true
            }
        }

        do {
            let base = try await CatalogClient.shared.getUserServiceURL()
            let url  = URL(string: "\(base)/getActiveRoom?user_id=\(userId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

            guard latestLoadID == loadID else { return }

            guard let activeRoomData = json?["active_room"] as? [String: Any],
                  let _ = activeRoomData["id"] as? Int else {
                hasActiveRoom = false
                hasData = false
                if !preserveVisibleState {
                    resetToDefaults()
                }
                return
            }
            hasActiveRoom = true

            // Build the date string for the query (YYYY-MM-DD)
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            let dateStr = formatter.string(from: date)

            // Fetch sleep analytics for the selected date
            let tsURL = try await CatalogClient.shared.getTimeSeriesURL()
            let analyticsURL = URL(string: "\(tsURL)/getSleepAnalyticsByDate?user_id=\(userId)&date=\(dateStr)")!
            let (analyticsData, _) = try await URLSession.shared.data(from: analyticsURL)
            let analytics = try JSONSerialization.jsonObject(with: analyticsData) as? [String: Any]

            guard latestLoadID == loadID else { return }

            // Check if we got an error or null response
            if let error = analytics?["error"] as? String {
                print("No sleep analytics found: \(error)")
                resetToDefaults()
                hasData = false
                return
            } else {
                print("Sleep analytics loaded successfully for date: \(dateStr)")
                if let analytics = analytics {
                    print("Raw analytics data: \(analytics)")
                }
            }

            // Parse the MongoDB document (stored as-is from MQTT payload)
            if let analytics = analytics {
                sleepScore     = analytics["sleep_score"] as? Double ?? 0
                sleepDuration  = analytics["sleep_hours"] as? Double ?? 0
                interruptions  = Double(analytics["wake_ups"] as? Int ?? 0)

                if let stagePct = analytics["stage_percent"] as? [String: Any] {
                    remSleep  = stagePct["REM"] as? Double ?? 0
                    deepSleep = stagePct["DEEP"] as? Double ?? 0
                } else {
                    remSleep  = 0
                    deepSleep = 0
                }

                if let stageMin = analytics["stage_minutes"] as? [String: Any] {
                    awakeMinutes = (stageMin["AWAKE"] as? NSNumber)?.doubleValue ?? 0
                    lightMinutes = (stageMin["LIGHT"] as? NSNumber)?.doubleValue ?? 0
                    deepMinutes  = (stageMin["DEEP"]  as? NSNumber)?.doubleValue ?? 0
                    remMinutes   = (stageMin["REM"]   as? NSNumber)?.doubleValue ?? 0
                } else {
                    awakeMinutes = 0
                    lightMinutes = 0
                    deepMinutes  = 0
                    remMinutes   = 0
                }

                hrv = analytics["hrv_rmssd_ms"] as? Double ?? 0
                rhr = analytics["resting_hr"] as? Double ?? 0
                hasData = true
            } else {
                resetToDefaults()
                hasData = false
            }
        } catch is CancellationError {
            return
        } catch let urlError as URLError where urlError.code == .cancelled {
            print("SleepDashboard request cancelled for date: \(date)")
            return
        } catch {
            print("SleepDashboard error: \(error)")
            guard latestLoadID == loadID else { return }
            if !preserveVisibleState {
                resetToDefaults()
                hasData = false
            }
        }
    }

    private func resetToDefaults() {
        sleepScore    = 0
        sleepDuration = 0
        interruptions = 0
        remSleep      = 0
        deepSleep     = 0
        awakeMinutes  = 0
        lightMinutes  = 0
        deepMinutes   = 0
        remMinutes    = 0
        hrv           = 0
        rhr           = 0
    }

    // MARK: - Computed labels

    var sleepQualityLabel: String {
        if !hasData {
            return "No Data Available"
        }

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
