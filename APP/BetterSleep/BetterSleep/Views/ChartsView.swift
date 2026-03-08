import SwiftUI
import Combine

// MARK: - ViewModel

@MainActor
class SleepDashboardModel: ObservableObject {
    @Published var isLoading = false
    @Published var sleepScore: Double = 0
    @Published var sleepDuration: Double = 0   // hours
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

// MARK: - Main View

struct ChartsView: View {
    @StateObject private var vm = SleepDashboardModel()

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [
                        Color(red: 0.04, green: 0.06, blue: 0.16),
                        Color(red: 0.07, green: 0.10, blue: 0.26)
                    ],
                    startPoint: .top, endPoint: .bottom
                )
                .ignoresSafeArea()

                if !vm.hasActiveRoom {
                    noActiveRoomView
                } else {
                    ScrollView {
                        VStack(spacing: 28) {
                            headerRow
                            sleepScoreGauge
                            metricsGrid
                            Spacer(minLength: 24)
                        }
                        .padding(.horizontal, 20)
                        .padding(.top, 4)
                    }
                }
            }
            .navigationTitle("Sleep Analysis")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
        .task { await vm.load() }
    }

    // MARK: Header

    private var headerRow: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Last Night")
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.5))
                Text(vm.lastNightLabel)
                    .font(.subheadline).fontWeight(.semibold)
                    .foregroundStyle(.white)
            }
            Spacer()
            Button { Task { await vm.load() } } label: {
                if vm.isLoading {
                    ProgressView().tint(.white)
                } else {
                    Image(systemName: "arrow.clockwise")
                        .foregroundStyle(.white.opacity(0.7))
                        .imageScale(.medium)
                }
            }
        }
    }

    // MARK: Gauge

    private var sleepScoreGauge: some View {
        VStack(spacing: 20) {
            ZStack {
                // Track
                Circle()
                    .trim(from: 0.0, to: 0.75)
                    .stroke(Color.white.opacity(0.08),
                            style: StrokeStyle(lineWidth: 20, lineCap: .round))
                    .rotationEffect(.degrees(135))
                    .frame(width: 230, height: 230)

                // Score arc
                Circle()
                    .trim(from: 0.0, to: 0.75 * (vm.sleepScore / 100))
                    .stroke(
                        LinearGradient(
                            colors: [.blue, .cyan, vm.sleepQualityColor],
                            startPoint: .leading, endPoint: .trailing
                        ),
                        style: StrokeStyle(lineWidth: 20, lineCap: .round)
                    )
                    .rotationEffect(.degrees(135))
                    .frame(width: 230, height: 230)
                    .animation(.easeOut(duration: 1.2), value: vm.sleepScore)

                // Center labels
                VStack(spacing: 2) {
                    Text("\(Int(vm.sleepScore))")
                        .font(.system(size: 60, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                    Text(vm.sleepQualityLabel)
                        .font(.subheadline).fontWeight(.semibold)
                        .foregroundStyle(vm.sleepQualityColor)
                    Text("Sleep Score")
                        .font(.caption2)
                        .foregroundStyle(.white.opacity(0.45))
                }
            }

            // Duration + quality summary
            HStack(spacing: 40) {
                sleepSummaryItem(
                    icon: "moon.fill",
                    iconColor: .indigo,
                    value: vm.sleepDuration > 0 ? String(format: "%.1fh", vm.sleepDuration) : "--",
                    label: "Duration"
                )
                Rectangle()
                    .frame(width: 1, height: 36)
                    .foregroundStyle(.white.opacity(0.15))
                sleepSummaryItem(
                    icon: "zzz",
                    iconColor: vm.sleepQualityColor,
                    value: vm.sleepQualityLabel,
                    label: "Quality"
                )
                Rectangle()
                    .frame(width: 1, height: 36)
                    .foregroundStyle(.white.opacity(0.15))
                sleepSummaryItem(
                    icon: "heart.fill",
                    iconColor: .red,
                    value: vm.avgHeartRate > 0 ? String(format: "%.0f", vm.avgHeartRate) : "--",
                    label: "Avg BPM"
                )
            }
        }
        .padding(.vertical, 8)
    }

    private func sleepSummaryItem(icon: String, iconColor: Color, value: String, label: String) -> some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .foregroundStyle(iconColor)
                .font(.system(size: 14))
            Text(value)
                .font(.system(size: 15, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.45))
        }
    }

    // MARK: Metrics Grid

    private var metricsGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
            SleepMetricCard(
                icon: "bed.double.fill", iconColor: .indigo,
                title: "Sleep",
                value: vm.sleepDuration > 0 ? String(format: "%.1f", vm.sleepDuration) : "--",
                unit: "hours",
                subtitle: vm.sleepDuration == 0 ? "No data"
                         : vm.sleepDuration >= 7  ? "Recommended ✓" : "Below target",
                accent: Color(red: 0.13, green: 0.14, blue: 0.32)
            )
            SleepMetricCard(
                icon: "heart.fill", iconColor: .red,
                title: "Heart Rate",
                value: vm.avgHeartRate > 0 ? String(format: "%.0f", vm.avgHeartRate) : "--",
                unit: "BPM",
                subtitle: "avg during sleep",
                accent: Color(red: 0.22, green: 0.08, blue: 0.10)
            )
            SleepMetricCard(
                icon: "arrow.down.heart.fill", iconColor: .pink,
                title: "Min HR",
                value: vm.minHeartRate > 0 ? String(format: "%.0f", vm.minHeartRate) : "--",
                unit: "BPM",
                subtitle: "resting low",
                accent: Color(red: 0.20, green: 0.07, blue: 0.14)
            )
            SleepMetricCard(
                icon: "arrow.up.heart.fill", iconColor: Color(red: 1, green: 0.45, blue: 0.3),
                title: "Max HR",
                value: vm.maxHeartRate > 0 ? String(format: "%.0f", vm.maxHeartRate) : "--",
                unit: "BPM",
                subtitle: "peak during sleep",
                accent: Color(red: 0.20, green: 0.09, blue: 0.06)
            )
            SleepMetricCard(
                icon: "waveform.path", iconColor: .purple,
                title: "Movement",
                value: vm.avgVibration < 0.001 ? "--" : String(format: "%.2f", vm.avgVibration),
                unit: "",
                subtitle: vm.movementLabel,
                accent: Color(red: 0.12, green: 0.07, blue: 0.20)
            )
            SleepMetricCard(
                icon: "thermometer.medium", iconColor: .orange,
                title: "Room Temp",
                value: vm.avgTemperature > 0 ? String(format: "%.1f", vm.avgTemperature) : "--",
                unit: "°C",
                subtitle: "during sleep",
                accent: Color(red: 0.20, green: 0.11, blue: 0.04)
            )
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

// MARK: - Metric Card Component

struct SleepMetricCard: View {
    let icon: String
    let iconColor: Color
    let title: String
    let value: String
    let unit: String
    let subtitle: String
    let accent: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(iconColor)
                Text(title)
                    .font(.caption).fontWeight(.semibold)
                    .foregroundStyle(iconColor)
                Spacer()
            }

            HStack(alignment: .lastTextBaseline, spacing: 3) {
                Text(value)
                    .font(.system(size: 34, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
                if !unit.isEmpty {
                    Text(unit)
                        .font(.caption)
                        .foregroundStyle(.white.opacity(0.55))
                        .padding(.bottom, 3)
                }
            }

            Text(subtitle)
                .font(.caption2)
                .foregroundStyle(.white.opacity(0.45))
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(accent)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.white.opacity(0.07), lineWidth: 1)
        )
    }
}

#Preview {
    ChartsView()
}
