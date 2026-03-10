import SwiftUI
import Combine

// MARK: - ViewModel

@MainActor
class SleepDashboardModel: ObservableObject {
    @Published var isLoading = false
    @Published var sleepScore: Double = 0
    @Published var sleepDuration: Double = 0   // hours
    @Published var interruptions: Double = 0   // count
    @Published var remSleep: Double = 0        // percentage
    @Published var deepSleep: Double = 0       // percentage
    @Published var hrv: Double = 0             // HRV
    @Published var rhr: Double = 0             // Resting Heart Rate
    @Published var avgHeartRate: Double = 0
    @Published var minHeartRate: Double = 0
    @Published var maxHeartRate: Double = 0
    @Published var avgVibration: Double = 0
    @Published var avgTemperature: Double = 0
    @Published var hasActiveRoom = true

    func load() async {
        guard let userIdStr = UserDefaults.standard.string(forKey: "currentUserId"),
              let userId = Int(userIdStr) else { return }

        isLoading = true
        defer { isLoading = false }

        do {
            // Resolve active room
            let base = try await CatalogClient.shared.getUserServiceURL()
            let url = URL(string: "\(base)/getActiveRoom?user_id=\(userId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]

            guard let activeRoomData = json?["active_room"] as? [String: Any],
                  let roomId = activeRoomData["id"] as? Int else {
                hasActiveRoom = false
                return
            }
            hasActiveRoom = true

            let (startTS, endTS) = lastNightWindow()
            let tsURL = try await CatalogClient.shared.getTimeSeriesURL()

            async let hrEvents    = fetchEvents(tsURL: tsURL, roomId: roomId, sensorType: 3)
            async let presEvents  = fetchEvents(tsURL: tsURL, roomId: roomId, sensorType: 2)
            async let vibEvents   = fetchEvents(tsURL: tsURL, roomId: roomId, sensorType: 4)
            async let tempEvents  = fetchEvents(tsURL: tsURL, roomId: roomId, sensorType: 0)

            let (hr, pres, vib, temp) = try await (hrEvents, presEvents, vibEvents, tempEvents)

            let hrNight   = hr.filter   { $0.t >= startTS && $0.t <= endTS }
            let presNight = pres.filter  { $0.t >= startTS && $0.t <= endTS }
            let vibNight  = vib.filter  { $0.t >= startTS && $0.t <= endTS }
            let tempNight = temp.filter { $0.t >= startTS && $0.t <= endTS }

            // Sleep duration: count 15-min presence=1 intervals
            let presenceOn = presNight.filter { $0.v >= 0.5 }
            sleepDuration = Double(presenceOn.count) * 15.0 / 60.0

            // Heart rate
            let hrValues = hrNight.map { $0.v }
            if !hrValues.isEmpty {
                avgHeartRate = hrValues.reduce(0, +) / Double(hrValues.count)
                minHeartRate = hrValues.min()!
                maxHeartRate = hrValues.max()!
            } else {
                avgHeartRate = 0; minHeartRate = 0; maxHeartRate = 0
            }

            // Movement
            let vibValues = vibNight.map { $0.v }
            avgVibration = vibValues.isEmpty ? 0 : vibValues.reduce(0, +) / Double(vibValues.count)

            // Temperature
            let tempValues = tempNight.map { $0.v }
            avgTemperature = tempValues.isEmpty ? 0 : tempValues.reduce(0, +) / Double(tempValues.count)

            sleepScore = computeScore()
        } catch {
            print("SleepDashboard error: \(error)")
        }
    }

    private func fetchEvents(tsURL: String, roomId: Int, sensorType: Int) async throws -> [SenMLEvent] {
        let url = URL(string: "\(tsURL)/getSensorByRoomAndType?room_id=\(roomId)&sensor_type=\(sensorType)")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let records = try JSONDecoder().decode([SenMLRecord].self, from: data)
        return records.flatMap { $0.e }
    }

    private func lastNightWindow() -> (Double, Double) {
        let cal = Calendar.current
        let now = Date()
        let hour = cal.component(.hour, from: now)
        let start: Date
        let end: Date
        if hour < 12 {
            // Morning → last night = yesterday 22:00–today 7:00
            let yesterday = cal.date(byAdding: .day, value: -1, to: now)!
            start = cal.date(bySettingHour: 22, minute: 0, second: 0, of: yesterday)!
            end   = cal.date(bySettingHour:  7, minute: 0, second: 0, of: now)!
        } else {
            // Daytime/evening → night before last
            let twoDaysAgo = cal.date(byAdding: .day, value: -2, to: now)!
            let yesterday  = cal.date(byAdding: .day, value: -1, to: now)!
            start = cal.date(bySettingHour: 22, minute: 0, second: 0, of: twoDaysAgo)!
            end   = cal.date(bySettingHour:  7, minute: 0, second: 0, of: yesterday)!
        }
        return (start.timeIntervalSince1970, end.timeIntervalSince1970)
    }

    private func computeScore() -> Double {
        var score = 0.0
        // Duration component (40 pts): target 8 h
        score += min(sleepDuration / 8.0, 1.0) * 40
        // Heart rate component (30 pts): ideal 50–65 bpm during sleep
        if avgHeartRate > 0 {
            if avgHeartRate >= 50 && avgHeartRate <= 65 {
                score += 30
            } else if avgHeartRate < 50 {
                score += max(0, 30 - (50 - avgHeartRate) * 2)
            } else {
                score += max(0, 30 - (avgHeartRate - 65) * 1.5)
            }
        }
        // Movement component (30 pts): lower = better
        score += avgVibration <= 0.1 ? 30 : max(0, 30 - avgVibration * 100)
        return min(score, 100)
    }

    var sleepQualityLabel: String {
        switch sleepScore {
        case 80...: return "Excellent"
        case 60..<80: return "Good"
        case 40..<60: return "Fair"
        default: return "Poor"
        }
    }

    var sleepQualityColor: Color {
        switch sleepScore {
        case 80...: return Color(red: 0.2,  green: 0.85, blue: 0.4)
        case 60..<80: return Color(red: 0.3,  green: 0.7,  blue: 1.0)
        case 40..<60: return Color(red: 1.0,  green: 0.7,  blue: 0.2)
        default:      return Color(red: 1.0,  green: 0.35, blue: 0.35)
        }
    }

    var movementLabel: String {
        if avgVibration < 0.001 { return "No data" }
        if avgVibration < 0.1   { return "Restful ✓" }
        if avgVibration < 0.3   { return "Some movement" }
        return "Restless"
    }

    var lastNightLabel: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, MMM d"
        let cal = Calendar.current
        let now = Date()
        let hour = cal.component(.hour, from: now)
        let ref = hour < 12
            ? cal.date(byAdding: .day, value: -1, to: now)!
            : cal.date(byAdding: .day, value: -2, to: now)!
        return formatter.string(from: ref)
    }
}

// MARK: - Metric Type Definition

enum SleepMetricType: Hashable {
    case duration, interruptions, remSleep, deepSleep, hrv, rhr

    var icon: String {
        switch self {
        case .duration: return "bed.double.fill"
        case .interruptions: return "moon.zzz.fill"
        case .remSleep: return "waveform.path"
        case .deepSleep: return "moon.fill"
        case .hrv: return "bolt.heart.fill"
        case .rhr: return "arrow.down.heart.fill"
        }
    }

    var iconColor: Color {
        switch self {
        case .duration: return .blue
        case .interruptions: return .orange
        case .remSleep: return .purple
        case .deepSleep: return .indigo
        case .hrv: return .red
        case .rhr: return .red
        }
    }

    var title: String {
        switch self {
        case .duration: return "Sleep Duration"
        case .interruptions: return "Interruptions"
        case .remSleep: return "REM Sleep"
        case .deepSleep: return "Deep Sleep"
        case .hrv: return "HRV"
        case .rhr: return "RHR"
        }
    }

    var subtitle: String {
        switch self {
        case .duration: return "Total hours asleep"
        case .interruptions: return "Times you woke up"
        case .remSleep: return "Percentage of night"
        case .deepSleep: return "Percentage of night"
        case .hrv: return "Heart rate variability"
        case .rhr: return "Resting heart rate"
        }
    }

    var useStackedValueLayout: Bool {
        return self == .interruptions || self == .remSleep || self == .deepSleep
    }
}

// MARK: - Main View

struct ChartsView: View {
    @StateObject private var vm: SleepDashboardModel
    private let shouldAutoLoad: Bool

    @MainActor
    init(shouldAutoLoad: Bool = true) {
        _vm = StateObject(wrappedValue: SleepDashboardModel())
        self.shouldAutoLoad = shouldAutoLoad
    }

    init(vm: SleepDashboardModel, shouldAutoLoad: Bool = true) {
        _vm = StateObject(wrappedValue: vm)
        self.shouldAutoLoad = shouldAutoLoad
    }

    var body: some View {
        NavigationStack {
            VStack {
                if !vm.hasActiveRoom {
                    noActiveRoomView
                } else {
                    List {
                        sleepScoreGauge
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                            

                        Section(header: Text("Sleep Metrics")) {
                            ForEach([SleepMetricType.duration, .interruptions, .remSleep, .deepSleep], id: \.self) { type in
                                metricRow(type: type, value: getMetricValue(type: type))
                            }
                        }

                        Section(header: Text("Heart Metrics")) {
                            ForEach([SleepMetricType.hrv, .rhr], id: \.self) { type in
                                metricRow(type: type, value: getMetricValue(type: type))
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                    .scrollIndicators(.hidden)
                }
            }
            .navigationTitle("Sleep Analysis")
        }
        .task {
            if shouldAutoLoad {
                await vm.load()
            }
        }
    }

    private func getMetricValue(type: SleepMetricType) -> Double {
        switch type {
        case .duration: return vm.sleepDuration
        case .interruptions: return vm.interruptions
        case .remSleep: return vm.remSleep
        case .deepSleep: return vm.deepSleep
        case .hrv: return vm.hrv
        case .rhr: return vm.rhr
        }
    }


    // MARK: Gauge

    private var sleepScoreGauge: some View {
        VStack(spacing: 20) {
            ZStack {
                // Track
                Circle()
                    .trim(from: 0.0, to: 0.75)
                    .stroke(Color.secondary.opacity(0.2),
                            style: StrokeStyle(lineWidth: 20, lineCap: .round))
                    .rotationEffect(.degrees(135))
                    .frame(width: 230, height: 230)

                // Score arc
                Circle()
                    .trim(from: 0.0, to: 0.75 * (vm.sleepScore / 100))
                    .stroke(
                        LinearGradient(
                            colors: [vm.sleepQualityColor, vm.sleepQualityColor.opacity(0.7)],
                            startPoint: .leading, endPoint: .trailing
                        ),
                        style: StrokeStyle(lineWidth: 20, lineCap: .round)
                    )
                    .shadow(color: vm.sleepQualityColor.opacity(0.8), radius: 30, x: 0, y: 0)
                    .rotationEffect(.degrees(135))
                    .frame(width: 230, height: 230)
                    .animation(.easeOut(duration: 1.2), value: vm.sleepScore)

                // Center labels
                VStack(spacing: 2) {
                    Text("\(Int(vm.sleepScore))")
                        .font(.system(size: 60, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.primary)
                    Text(vm.sleepQualityLabel)
                        .font(.subheadline).fontWeight(.semibold).fontDesign(.rounded)
                        .foregroundStyle(vm.sleepQualityColor)
                    Text("Sleep Score")
                        .font(.caption).fontWeight(.semibold).fontDesign(.rounded)
                        .foregroundStyle(Color.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 32)
    }

    // MARK: - Metric Row

    private func metricRow(type: SleepMetricType, value: Double) -> some View {
        let (displayValue, unit) = formatMetricValue(type: type, value: value)

        return HStack(spacing: 14) {
            Image(systemName: type.icon)
                .font(.title)
                .foregroundColor(type.iconColor)
                .shadow(color: type.iconColor.opacity(0.7), radius: 10, x: 0, y: 0)
                .frame(width: 36)

            VStack(alignment: .leading, spacing: 3) {
                Text(type.title)
                    .font(.headline)
                    .fontWeight(.semibold)
                    .fontDesign(.rounded)
                Text(type.subtitle)
                    .font(.caption)
                    .fontDesign(.rounded)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if type.useStackedValueLayout {
                HStack(spacing: 2) {
                    Text(displayValue)
                        .font(.title3)
                        .fontWeight(.bold)
                        .foregroundStyle(.primary)
                        .fontDesign(.rounded)
                    
                    if !unit.isEmpty {
                        Text(unit)
                            .fontDesign(.rounded)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                HStack(spacing: 2) {
                    Text(displayValue)
                        .fontWeight(.bold)
                        .foregroundStyle(.primary)
                    
                    if !unit.isEmpty {
                        Text(unit)
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.title3).fontDesign(.rounded)
            }
        }
        .padding(.vertical, 6)
    }

    private func formatMetricValue(type: SleepMetricType, value: Double) -> (String, String) {
        switch type {
        case .duration:
            if value > 0 {
                let hours = Int(value)
                let minutes = Int((value - Double(hours)) * 60)
                return ("\(hours)h \(minutes)m", "hours")
            }
            return ("--", "")
        case .interruptions:
            return (value > 0 ? String(format: "%.0f", value) : "--", "times")
        case .remSleep:
            return (value > 0 ? String(format: "%.0f", value) : "--", "%")
        case .deepSleep:
            return (value > 0 ? String(format: "%.0f", value) : "--", "%")
        case .hrv:
            return (value > 0 ? String(format: "%.0f", value) : "--", "ms")
        case .rhr:
            return (value > 0 ? String(format: "%.0f", value) : "--", "bpm")
        }
    }

    // MARK: No Active Room

    private var noActiveRoomView: some View {
        VStack(spacing: 16) {
            Image(systemName: "moon.zzz.fill")
                .font(.system(size: 56))
                .foregroundStyle(.white.opacity(0.3))
            Text("No Active Room")
                .font(.title2).fontWeight(.semibold)
                .foregroundStyle(.white)
            Text("Set a room as active in My Homes\nto see your sleep analytics.")
                .font(.subheadline)
                .foregroundStyle(.white.opacity(0.5))
                .multilineTextAlignment(.center)
        }
    }
}


private func makePreviewVM(
    score: Double,
    duration: Double,
    interruptions: Double = 2,
    remSleep: Double = 20,
    deepSleep: Double = 15,
    hrv: Double = 50,
    rhr: Double = 16,
    avgHR: Double = 58,
    minHR: Double = 49,
    maxHR: Double = 72,
    vibration: Double = 0.08,
    temperature: Double = 20.8,
    hasActiveRoom: Bool = true
) -> SleepDashboardModel {
    let vm = SleepDashboardModel()
    vm.hasActiveRoom = hasActiveRoom
    vm.sleepScore = score
    vm.sleepDuration = duration
    vm.interruptions = interruptions
    vm.remSleep = remSleep
    vm.deepSleep = deepSleep
    vm.hrv = hrv
    vm.rhr = rhr
    vm.avgHeartRate = avgHR
    vm.minHeartRate = minHR
    vm.maxHeartRate = maxHR
    vm.avgVibration = vibration
    vm.avgTemperature = temperature
    return vm
}

#Preview("Excellent") {
    ChartsView(
        vm: makePreviewVM(
            score: 88,
            duration: 8.0,
            interruptions: 1,
            remSleep: 22,
            deepSleep: 18,
            hrv: 65,
            rhr: 15
        ),
        shouldAutoLoad: false
    )
}

#Preview("Good") {
    ChartsView(
        vm: makePreviewVM(
            score: 72,
            duration: 6.9,
            interruptions: 2,
            remSleep: 20,
            deepSleep: 14,
            hrv: 55,
            rhr: 16
        ),
        shouldAutoLoad: false
    )
}

#Preview("Fair") {
    ChartsView(
        vm: makePreviewVM(
            score: 52,
            duration: 5.8,
            interruptions: 4,
            remSleep: 16,
            deepSleep: 10,
            hrv: 40,
            rhr: 18
        ),
        shouldAutoLoad: false
    )
}

#Preview("Poor") {
    ChartsView(
        vm: makePreviewVM(
            score: 28,
            duration: 3.9,
            interruptions: 7,
            remSleep: 12,
            deepSleep: 5,
            hrv: 25,
            rhr: 22
        ),
        shouldAutoLoad: false
    )
}

#Preview("No Data") {
    ChartsView(
        vm: makePreviewVM(
            score: 0,
            duration: 0,
            interruptions: 0,
            remSleep: 0,
            deepSleep: 0,
            hrv: 0,
            rhr: 0
        ),
        shouldAutoLoad: false
    )
}
