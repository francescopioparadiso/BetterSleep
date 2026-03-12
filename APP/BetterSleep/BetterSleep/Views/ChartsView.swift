import SwiftUI

// MARK: - Main View

struct ChartsView: View {
    @StateObject private var vm: ChartsModel
    private let shouldAutoLoad: Bool

    @MainActor
    init(shouldAutoLoad: Bool = true) {
        _vm = StateObject(wrappedValue: ChartsModel())
        self.shouldAutoLoad = shouldAutoLoad
    }

    init(vm: ChartsModel, shouldAutoLoad: Bool = true) {
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
                                metricRow(type: type, value: metricValue(for: type))
                            }
                        }

                        Section(header: Text("Heart Metrics")) {
                            ForEach([SleepMetricType.hrv, .rhr], id: \.self) { type in
                                metricRow(type: type, value: metricValue(for: type))
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
            if shouldAutoLoad { await vm.load() }
        }
    }

    private func metricValue(for type: SleepMetricType) -> Double {
        switch type {
        case .duration:      return vm.sleepDuration
        case .interruptions: return vm.interruptions
        case .remSleep:      return vm.remSleep
        case .deepSleep:     return vm.deepSleep
        case .hrv:           return vm.hrv
        case .rhr:           return vm.rhr
        }
    }

    // MARK: - Gauge

    private var sleepScoreGauge: some View {
        ZStack {
            Circle()
                .trim(from: 0.0, to: 0.75)
                .stroke(Color.secondary.opacity(0.2),
                        style: StrokeStyle(lineWidth: 20, lineCap: .round))
                .rotationEffect(.degrees(135))
                .frame(width: 230, height: 230)

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
        .frame(maxWidth: .infinity)
        .padding(.vertical, 32)
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
                    .font(.headline).fontWeight(.semibold).fontDesign(.rounded)
                Text(type.subtitle)
                    .font(.caption).fontDesign(.rounded).foregroundStyle(.secondary)
            }

            Spacer()

            HStack(spacing: 2) {
                Text(displayValue)
                    .font(.title3).fontWeight(.bold).fontDesign(.rounded)
                    .foregroundStyle(.primary)
                if !unit.isEmpty {
                    Text(unit)
                        .font(.title3).fontDesign(.rounded).foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 6)
    }

    private func formatMetricValue(type: SleepMetricType, value: Double) -> (String, String) {
        switch type {
        case .duration:
            guard value > 0 else { return ("--", "") }
            let hours   = Int(value)
            let minutes = Int((value - Double(hours)) * 60)
            return ("\(hours)h \(minutes)m", "")
        case .interruptions: return (value > 0 ? String(format: "%.0f", value) : "--", "times")
        case .remSleep:      return (value > 0 ? String(format: "%.0f", value) : "--", "%")
        case .deepSleep:     return (value > 0 ? String(format: "%.0f", value) : "--", "%")
        case .hrv:           return (value > 0 ? String(format: "%.0f", value) : "--", "ms")
        case .rhr:           return (value > 0 ? String(format: "%.0f", value) : "--", "bpm")
        }
    }

    // MARK: - No Active Room

    private var noActiveRoomView: some View {
        VStack(spacing: 16) {
            Image(systemName: "moon.zzz.fill")
                .font(.system(size: 56))
                .foregroundStyle(.secondary)
            Text("No Active Room")
                .font(.title2).fontWeight(.semibold)
            Text("Set a room as active in My Homes\nto see your sleep analytics.")
                .font(.subheadline).foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
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
    hasActiveRoom: Bool = true
) -> ChartsModel {
    let vm = ChartsModel()
    vm.hasActiveRoom = hasActiveRoom
    vm.sleepScore = score
    vm.sleepDuration = duration
    vm.interruptions = interruptions
    vm.remSleep = remSleep
    vm.deepSleep = deepSleep
    vm.hrv = hrv
    vm.rhr = rhr
    return vm
}

#Preview("Excellent") {
    ChartsView(vm: makePreviewVM(score: 88, duration: 8.0, interruptions: 1,
                                 remSleep: 22, deepSleep: 18, hrv: 65, rhr: 15),
               shouldAutoLoad: false)
}

#Preview("Good") {
    ChartsView(vm: makePreviewVM(score: 72, duration: 6.9, interruptions: 2,
                                 remSleep: 20, deepSleep: 14, hrv: 55, rhr: 16),
               shouldAutoLoad: false)
}

#Preview("Fair") {
    ChartsView(vm: makePreviewVM(score: 52, duration: 5.8, interruptions: 4,
                                 remSleep: 16, deepSleep: 10, hrv: 40, rhr: 18),
               shouldAutoLoad: false)
}

#Preview("Poor") {
    ChartsView(vm: makePreviewVM(score: 28, duration: 3.9, interruptions: 7,
                                 remSleep: 12, deepSleep: 5,  hrv: 25, rhr: 22),
               shouldAutoLoad: false)
}

#Preview("No Data") {
    ChartsView(vm: makePreviewVM(score: 0, duration: 0, interruptions: 0,
                                 remSleep: 0, deepSleep: 0, hrv: 0, rhr: 0),
               shouldAutoLoad: false)
}

#Preview("No Active Room") {
    ChartsView(vm: makePreviewVM(score: 0, duration: 0, hasActiveRoom: false),
               shouldAutoLoad: false)
}
