import SwiftUI
import UIKit

// MARK: - Sleep Stage Types

enum SleepStage: String, CaseIterable, Identifiable {
    case awake = "Awake"
    case rem = "REM"
    case light = "Light"
    case deep = "Deep"
    
    var id: String { self.rawValue }
    
    var color: Color {
        switch self {
        case .awake: return Color(red: 1.0, green: 0.5, blue: 0.4) // Salmon/Red
        case .rem: return Color(red: 0.4, green: 0.8, blue: 1.0)   // Light Blue
        case .light: return Color(red: 0.2, green: 0.5, blue: 0.9) // Medium Blue
        case .deep: return Color(red: 0.1, green: 0.2, blue: 0.6)  // Dark Blue
        }
    }
}

struct SleepStageData: Identifiable {
    let stage: SleepStage
    let minutes: Double

    var id: String { stage.rawValue }
}

private struct GaugePlaceholderState {
    let title: String
    let systemImage: String
    let description: String
    let color: Color
}

// MARK: - Main View

struct ChartsView: View {
    @StateObject private var vm: ChartsModel
    private let shouldAutoLoad: Bool

    @State private var currentWeekIndex = 0

    private let calendar: Calendar = {
        var cal = Calendar.current
        cal.firstWeekday = 2
        return cal
    }()

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
            VStack(spacing: 0) {
                dateHeader
                    .padding(.horizontal).padding(.vertical, 8)
                    .background(Color(uiColor: .systemGroupedBackground))

                Group {
                    if vm.shouldShowBlockingLoader {
                        ProgressView("Loading sleep data...")
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else if !vm.hasActiveRoom {
                        ContentUnavailableView(
                            "No Active Room",
                            systemImage: "moon.zzz.fill",
                            description: Text("Set a room as active in My Homes to see your sleep analytics.")
                        )
                        .symbolRenderingMode(.hierarchical)
                        .foregroundStyle(.indigo)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .offset(y: -36)
                    } else {
                        List {
                            sleepScoreGauge
                                .listRowSeparator(.hidden)
                                .listRowBackground(Color.clear)

                            Section(header: Text("Sleep Stages")) {
                                SleepStageChart(data: [
                                    SleepStageData(stage: .deep, minutes: vm.deepMinutes),
                                    SleepStageData(stage: .light, minutes: vm.lightMinutes),
                                    SleepStageData(stage: .rem, minutes: vm.remMinutes),
                                    SleepStageData(stage: .awake, minutes: vm.awakeMinutes)
                                ])
                                .padding(.vertical, 8)
                            }

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
                        .refreshable {
                            await vm.refresh()
                        }
                    }
                }
            }
            .background(Color(uiColor: .systemGroupedBackground))
        }
        .task {
            currentWeekIndex = weekOffset(for: vm.selectedDate)
            if shouldAutoLoad { await vm.load() }
        }
        .onChange(of: vm.selectedDate) { _, newDate in
            let nextWeekIndex = weekOffset(for: newDate)
            if nextWeekIndex != currentWeekIndex {
                currentWeekIndex = nextWeekIndex
            }
            Task { await vm.load(for: vm.selectedDate) }
        }
        .onChange(of: currentWeekIndex) { _, newWeekIndex in
            let currentWeekMonday = startOfWeek(for: weekOffset(for: vm.selectedDate))
            let dayOffset = calendar.dateComponents([.day], from: currentWeekMonday, to: vm.selectedDate).day ?? 0
            let newWeekMonday = startOfWeek(for: newWeekIndex)
            let nextDate = calendar.date(byAdding: .day, value: dayOffset, to: newWeekMonday) ?? vm.selectedDate

            if !calendar.isDate(nextDate, inSameDayAs: vm.selectedDate) {
                withAnimation(.snappy) {
                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                    vm.selectedDate = nextDate
                }
            }
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

    @ViewBuilder
    private var dateHeader: some View {
        VStack(spacing: 8) {
            HStack {
                if !calendar.isDateInToday(vm.selectedDate) {
                    Image(systemName: "circle.fill")
                        .foregroundStyle(Color.red)
                }

                Text(vm.selectedDate, format: .dateTime.weekday().month().day())
                    .font(.title)
                    .fontDesign(.rounded)
                    .fontWeight(.bold)
                    .contentTransition(.numericText(value: Double(vm.selectedDate.timeIntervalSince1970)))
                    .animation(.snappy, value: vm.selectedDate)

                Spacer()
            }
            .contentShape(Rectangle())
            .onTapGesture {
                withAnimation(.snappy) {
                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                    vm.selectedDate = Date()
                    currentWeekIndex = 0
                }
            }

            TabView(selection: $currentWeekIndex) {
                ForEach(-20...20, id: \.self) { weekOffset in
                    HStack(spacing: 8) {
                        ForEach(0..<7, id: \.self) { index in
                            let weekStart = startOfWeek(for: weekOffset)
                            let date = calendar.date(byAdding: .day, value: index, to: weekStart) ?? vm.selectedDate
                            let isDateSelected = calendar.isDate(date, inSameDayAs: vm.selectedDate)
                            let isToday = calendar.isDateInToday(date)

                            Button {
                                withAnimation(.snappy) {
                                    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                                    vm.selectedDate = date
                                }
                            } label: {
                                VStack(spacing: 6) {
                                    Text(date, format: .dateTime.day())
                                        .font(.title3)
                                        .fontDesign(.rounded)
                                        .fontWeight(isDateSelected ? .bold : .medium)
                                        .foregroundStyle(isDateSelected ? .primary : .secondary)

                                    Text(date, format: .dateTime.weekday())
                                        .font(.system(size: 10, weight: .bold, design: .rounded))
                                        .textCase(.uppercase)
                                        .foregroundStyle(isDateSelected ? .red : .secondary.opacity(0.5))
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 12)
                                .background {
                                    if isToday && !isDateSelected {
                                        RoundedRectangle(cornerRadius: 14)
                                            .fill(Color.secondary.opacity(0.1))
                                    }
                                }
                                .overlay(
                                    RoundedRectangle(cornerRadius: 14)
                                        .stroke(Color.secondary.opacity(0.3), lineWidth: isDateSelected ? 1.5 : 0)
                                )
                                .scaleEffect(isDateSelected ? 1.1 : 1.0)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.horizontal, 4)
                    .tag(weekOffset)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
            .frame(height: 80)
        }
        .padding(.top, 4)
    }

    // MARK: - Gauge

    private var sleepScoreGauge: some View {
        let placeholder = gaugePlaceholderState

        return ZStack {
            Circle()
                .trim(from: 0.0, to: 0.75)
                .stroke(Color.secondary.opacity(0.2),
                        style: StrokeStyle(lineWidth: 20, lineCap: .round))
                .rotationEffect(.degrees(135))
                .frame(width: 230, height: 230)

            Circle()
                .trim(from: 0.0, to: 0.75 * (placeholder == nil ? (vm.sleepScore / 100) : 0))
                .stroke(
                    LinearGradient(
                        colors: [vm.sleepQualityColor, vm.sleepQualityColor.opacity(0.7)],
                        startPoint: .leading, endPoint: .trailing
                    ),
                    style: StrokeStyle(lineWidth: 20, lineCap: .round)
                )
                .shadow(color: vm.sleepQualityColor.opacity(0.8), radius: 10, x: 0, y: 0)
                .rotationEffect(.degrees(135))
                .frame(width: 230, height: 230)
                .animation(.easeOut(duration: 0.7), value: vm.sleepScore)

            if let placeholder {
                VStack(spacing: 10) {
                    Image(systemName: placeholder.systemImage)
                        .font(.system(size: 34, weight: .semibold))
                        .foregroundStyle(placeholder.color)
                        .shadow(color: placeholder.color.opacity(0.35), radius: 10, x: 0, y: 0)

                    Text(placeholder.title)
                        .font(.title3)
                        .fontWeight(.bold)
                        .fontDesign(.rounded)
                        .multilineTextAlignment(.center)

                    Text(placeholder.description)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .fontDesign(.rounded)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 170)
                }
                .padding(.horizontal, 12)
            } else {
                VStack(spacing: 2) {
                    Text("\(Int(vm.sleepScore))")
                        .font(.system(size: 60, weight: .bold, design: .rounded))
                        .foregroundStyle(Color.primary)
                        .contentTransition(.numericText(value: vm.sleepScore))
                        .animation(.easeOut(duration: 0.7), value: vm.sleepScore)
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
        .padding(.top, 16)
        .padding(.bottom, placeholder == nil ? 0 : 12)
    }

    // MARK: - Metric Row

    private func metricRow(type: SleepMetricType, value: Double) -> some View {
        let (displayValue, unit) = formatMetricValue(type: type, value: value)

        return HStack(spacing: 14) {
            Image(systemName: type.icon)
                .font(.title)
                .foregroundColor(type.iconColor)
                .shadow(color: type.iconColor.opacity(0.7), radius: 5, x: 0, y: 0)
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
                    .contentTransition(.numericText(value: value))
                    .animation(.easeOut(duration: 0.7), value: value)
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
        case .interruptions: return (value > 0 ? String(format: "%.0f", value) : "0", "times")
        case .remSleep:      return (value > 0 ? String(format: "%.0f", value) : "--", "%")
        case .deepSleep:     return (value > 0 ? String(format: "%.0f", value) : "--", "%")
        case .hrv:           return (value > 0 ? String(format: "%.0f", value) : "--", "ms")
        case .rhr:           return (value > 0 ? String(format: "%.0f", value) : "--", "bpm")
        }
    }

    private var gaugePlaceholderState: GaugePlaceholderState? {
        if !vm.hasActiveRoom {
            return GaugePlaceholderState(
                title: "No Active Room",
                systemImage: "moon.zzz.fill",
                description: "Set a room as active in My Homes to see your sleep analytics.",
                color: .indigo
            )
        }

        return nil
    }

    private func startOfWeek(for offset: Int) -> Date {
        let mondayComponents = calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: Date())
        let currentWeekMonday = calendar.date(from: mondayComponents) ?? Date()
        return calendar.date(byAdding: .weekOfYear, value: offset, to: currentWeekMonday) ?? currentWeekMonday
    }

    private func weekOffset(for date: Date) -> Int {
        let todayWeekStart = startOfWeek(for: 0)
        let selectedWeekStart = calendar.date(from: calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: date)) ?? todayWeekStart
        return calendar.dateComponents([.weekOfYear], from: todayWeekStart, to: selectedWeekStart).weekOfYear ?? 0
    }
}

// MARK: - Sleep Stage Chart

struct SleepStageChart: View {
    let data: [SleepStageData]

    private let durationColumnWidth: CGFloat = 60
    
    var body: some View {
        VStack(spacing: 0) {
            ForEach(data) { item in
                SleepStageRow(
                    item: item,
                    maxMinutes: max(data.map(\.minutes).max() ?? 1, 1),
                    durationColumnWidth: durationColumnWidth
                )
                .padding(.vertical, 4)
                .padding(.horizontal, 4)
            }
        }
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .animation(.easeOut(duration: 0.7), value: data.map(\.minutes))
    }

    private static func formattedDuration(minutes: Double) -> String {
        let totalMinutes = Int(minutes)
        let hours = totalMinutes / 60
        let mins = totalMinutes % 60

        if hours > 0 {
            return mins > 0 ? "\(hours)h\(mins)m" : "\(hours)h"
        }

        return "\(mins)m"
    }

    private struct SleepStageRow: View {
        let item: SleepStageData
        let maxMinutes: Double
        let durationColumnWidth: CGFloat

        var body: some View {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(item.stage.rawValue)
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .fontDesign(.rounded)
                        .foregroundStyle(.secondary)

                    Spacer()

                    Text(SleepStageChart.formattedDuration(minutes: item.minutes))
                        .font(.subheadline)
                        .fontDesign(.rounded)
                        .foregroundStyle(.secondary)
                        .frame(width: durationColumnWidth, alignment: .trailing)
                        .contentTransition(.numericText(value: item.minutes))
                        .animation(.easeOut(duration: 0.7), value: item.minutes)
                }

                GeometryReader { proxy in
                    let fullWidth = max(proxy.size.width, 1)
                    let ratio = min(max(item.minutes / maxMinutes, 0), 1)
                    let barWidth = max(12, fullWidth * ratio)
                    let rowHeight: CGFloat = 24

                    RoundedRectangle(cornerRadius: 8)
                        .fill(item.stage.color)
                        .frame(width: item.minutes > 0 ? barWidth : 0, height: rowHeight)
                }
                .frame(height: 32)
            }
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
    hasActiveRoom: Bool = true,
    hasData: Bool = true
) -> ChartsModel {
    let vm = ChartsModel()
    vm.hasActiveRoom = hasActiveRoom
    vm.hasData = hasData
    vm.sleepScore = score
    vm.sleepDuration = duration
    vm.interruptions = interruptions
    vm.remSleep = remSleep
    vm.deepSleep = deepSleep
    vm.awakeMinutes = 15
    vm.lightMinutes = 200
    vm.deepMinutes = deepSleep * duration * 60 / 100
    vm.remMinutes = remSleep * duration * 60 / 100
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
                                 remSleep: 0, deepSleep: 0, hrv: 0, rhr: 0,
                                 hasData: false),
               shouldAutoLoad: false)
}

#Preview("No Active Room") {
    ChartsView(vm: makePreviewVM(score: 0, duration: 0, hasActiveRoom: false),
               shouldAutoLoad: false)
}
