import Foundation
import Supabase
import SwiftUI
import Combine

@MainActor
class DashboardViewModel: ObservableObject {
    @Published var sleepScore: Int = 0
    @Published var sleepSegments: [SleepSegment] = []
    @Published var isLoading = false
    
    // Summary statistics
    @Published var totalTimeInBed: String = "--"
    @Published var deepSleepTime: String = "--"
    @Published var avgHeartRate: String = "--"
    @Published var rhr: String = "--" // NEW
    @Published var hrv: String = "--" // NEW
    
    @Published var targetDate: Date = Date()
    
    @Published var chartBedtime: Date = Date()
    @Published var chartWakeTime: Date = Date()
    
    var isToday: Bool {
        Calendar.current.isDateInToday(targetDate)
    }
    
    func changeDate(by days: Int) {
        if let newDate = Calendar.current.date(byAdding: .day, value: days, to: targetDate) {
            if newDate <= Date() || Calendar.current.isDateInToday(newDate) {
                targetDate = newDate
                Task { await fetchLatestSleepData() }
            }
        }
    }
    
    func fetchLatestSleepData() async {
        isLoading = true
        
        do {
            let session = try await supabase.auth.session
            let userId = session.user.id
            
            // 1. FETCH GLOBAL PREFERENCES
            let prefs: [GlobalPreference] = try await supabase
                .from("global_preferences")
                .select()
                .eq("user_id", value: userId)
                .execute()
                .value
            
            // Set defaults if the user hasn't configured them yet
            let bedTimeStr = prefs.first?.bedtime ?? "22:00:00"
            let wakeTimeStr = prefs.first?.wake_time ?? "07:00:00"
            
            // Calculate exact boundaries based on target date
            let parsedWake = parseTime(wakeTimeStr, baseDate: targetDate)
            let parsedBed = parseTime(bedTimeStr, baseDate: targetDate)
            
            self.chartWakeTime = parsedWake
            // If bedtime is numerically greater than wake time (e.g. 22:00 > 07:00),
            // it means they went to bed the previous night!
            if parsedBed > parsedWake {
                self.chartBedtime = Calendar.current.date(byAdding: .day, value: -1, to: parsedBed)!
            } else {
                self.chartBedtime = parsedBed
            }
            
            // 2. FETCH SENSORS
            let sensors: [Sensor] = try await supabase
                .from("sensors")
                .select("*, rooms!inner(user_id)")
                .eq("rooms.user_id", value: userId)
                .execute()
                .value
            
            guard !sensors.isEmpty else {
                isLoading = false
                return
            }
            
            let sensorMap = Dictionary(uniqueKeysWithValues: sensors.map { ($0.id!, $0.sensor_type) })
            let sensorIds = sensors.map { $0.id! }
            
            // 3. FETCH LOGS (Massive 8-hour buffer to catch early bedtimes and late sleep-ins!)
            let queryStart = Calendar.current.date(byAdding: .hour, value: -8, to: self.chartBedtime)!
            let queryEnd = Calendar.current.date(byAdding: .hour, value: 8, to: self.chartWakeTime)!
            
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let startString = formatter.string(from: queryStart)
            let endString = formatter.string(from: queryEnd)
            
            let logs: [SensorDataLog] = try await supabase
                .from("sensor_data")
                .select()
                .in("sensor_id", values: sensorIds)
                .gte("created_at", value: startString)
                .lte("created_at", value: endString)
                .order("created_at", ascending: true)
                .execute()
                .value
            
            // 4. PROCESS DATA
            let result = SleepAlgorithmService.shared.processSleepData(logs: logs, sensorTypes: sensorMap)
            
            self.sleepScore = result.score
            self.sleepSegments = result.segments
            calculateStats(segments: result.segments, logs: logs, sensorMap: sensorMap)
            
        } catch {
            print("❌ Error: \(error)")
        }
        isLoading = false
    }

    // Helper to safely convert Supabase "14:30:00" strings into proper Swift Dates
    private func parseTime(_ timeStr: String, baseDate: Date) -> Date {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        guard let parsedTime = formatter.date(from: timeStr) else { return baseDate }
        
        let timeComponents = Calendar.current.dateComponents([.hour, .minute], from: parsedTime)
        var baseComponents = Calendar.current.dateComponents([.year, .month, .day], from: baseDate)
        baseComponents.hour = timeComponents.hour
        baseComponents.minute = timeComponents.minute
        
        return Calendar.current.date(from: baseComponents) ?? baseDate
    }
    
    private func calculateStats(segments: [SleepSegment], logs: [SensorDataLog], sensorMap: [UUID: SensorType]) {
            // Calculate Time in Bed using exact date durations
            let inBedMinutes = Int(segments.filter { $0.stage != .awake }.reduce(0) { $0 + $1.endDate.timeIntervalSince($1.startDate) } / 60)
            self.totalTimeInBed = "\(inBedMinutes / 60)h \(inBedMinutes % 60)m"
            
            // Calculate Deep Sleep using exact date durations
            let deepMinutes = Int(segments.filter { $0.stage == .deep }.reduce(0) { $0 + $1.endDate.timeIntervalSince($1.startDate) } / 60)
            self.deepSleepTime = "\(deepMinutes / 60)h \(deepMinutes % 60)m"
            
            // --- HR Math Stays Exactly the Same ---
            let hrValues = logs.filter { sensorMap[$0.sensor_id] == .hr }.map { $0.value }
            if !hrValues.isEmpty {
                let meanHR = hrValues.reduce(0, +) / Double(hrValues.count)
                self.avgHeartRate = "\(Int(meanHR)) bpm"
                
                let sortedHR = hrValues.sorted()
                let lowest20PercentCount = max(1, Int(Double(sortedHR.count) * 0.2))
                let lowestHRs = Array(sortedHR.prefix(lowest20PercentCount))
                let rhrValue = Int(lowestHRs.reduce(0, +) / Double(lowestHRs.count))
                self.rhr = "\(rhrValue) bpm"
                
                let variance = hrValues.map { pow($0 - meanHR, 2.0) }.reduce(0, +) / Double(hrValues.count)
                let simulatedHRV = Int(max(20, min(150, (sqrt(variance) * 2.5) + 30)))
                self.hrv = "\(simulatedHRV) ms"
            } else {
                self.avgHeartRate = "--"
                self.rhr = "--"
                self.hrv = "--"
            }
        }
}
