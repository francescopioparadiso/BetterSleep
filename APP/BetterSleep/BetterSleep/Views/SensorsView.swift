import SwiftUI
import Charts

// Sensor sort order: temperature first, light second, then the rest
private let sensorSortOrder: [String] = [
    "ambient_temp", "light", "humidity", "heart_rate", "vibration", "presence"
]

// MARK: - Sensors List View
struct SensorsView: View {
    let house: House
    @Binding var room: Room
    @StateObject private var sensorModel = SensorModel()
    @ObservedObject var roomModel: RoomModel

    private var sortedSensors: [Sensor] {
        sensorModel.sensors.sorted { a, b in
            let ia = sensorSortOrder.firstIndex(of: a.type) ?? 99
            let ib = sensorSortOrder.firstIndex(of: b.type) ?? 99
            return ia < ib
        }
    }

    var body: some View {
        Group {
            if sensorModel.isLoading {
                ProgressView("Loading sensors...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if sensorModel.sensors.isEmpty {
                GeometryReader { proxy in
                    ScrollView {
                        unavailableContent
                            .frame(maxWidth: .infinity)
                            .frame(minHeight: proxy.size.height)
                    }
                    .scrollIndicators(.hidden)
                    .refreshable {
                        await refreshData()
                    }
                }
            } else {
                List {
                    ForEach(sortedSensors) { sensor in
                        let sType = sensor.sensorType ?? .ambient_temp

                        Section {
                            // Row: Icon + name → navigates to detail
                            NavigationLink(destination: SensorDetailView(sensor: sensor, sensorModel: sensorModel)) {
                                HStack(spacing: 14) {
                                    Image(systemName: sType.icon)
                                        .font(.title2)
                                        .symbolColorRenderingMode(.gradient)
                                        .foregroundColor(sType.color)
                                        .frame(width: 36)
                                        .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))

                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(sensor.name)
                                            .font(.headline)
                                            .fontDesign(.rounded)
                                        Text(sType.label)
                                            .font(.caption)
                                            .fontDesign(.rounded)
                                            .foregroundColor(.secondary)
                                    }
                                }
                                .padding(.vertical, 4)
                            }

                            // Sliders for temperature
                            if sType == .ambient_temp {
                                VStack(alignment: .leading, spacing: 16) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Image(systemName: "moon.stars.fill")
                                                .foregroundColor(.indigo)
                                                .symbolColorRenderingMode(.gradient)
                                                .shadow(color: .indigo, radius: 10, x: 0, y: 0)
                                                .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))

                                            Text("Night: \(room.temperature_night ?? 18)°C")
                                                .font(.subheadline)
                                                .fontWeight(.bold)
                                                .fontDesign(.rounded)
                                        }
                                        Slider(
                                            value: Binding(
                                                get: { Double(room.temperature_night ?? 18) },
                                                set: { room.temperature_night = Int($0); roomModel.updateRoomDebounced(room) }
                                            ),
                                            in: 15...30, step: 1
                                        ).tint(.indigo)
                                    }
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Image(systemName: "sun.max.fill")
                                                .foregroundColor(.orange)
                                                .symbolColorRenderingMode(.gradient)
                                                .shadow(color: .orange, radius: 10, x: 0, y: 0)
                                                .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))
                                            
                                            Text("Morning: \(room.temperature_morning ?? 22)°C")
                                                .font(.subheadline)
                                                .fontWeight(.bold)
                                                .fontDesign(.rounded)
                                        }
                                        Slider(
                                            value: Binding(
                                                get: { Double(room.temperature_morning ?? 22) },
                                                set: { room.temperature_morning = Int($0); roomModel.updateRoomDebounced(room) }
                                            ),
                                            in: 15...30, step: 1
                                        ).tint(.orange)
                                    }
                                }
                            }

                            // Sliders for light
                            if sType == .light {
                                VStack(alignment: .leading, spacing: 16) {
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Image(systemName: "moon.stars.fill")
                                                .foregroundColor(.indigo)
                                                .symbolColorRenderingMode(.gradient)
                                                .shadow(color: .indigo, radius: 10, x: 0, y: 0)
                                                .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))
                                            Text("Night: \(room.light_night ?? 0)%")
                                                .font(.subheadline)
                                                .fontWeight(.bold)
                                                .fontDesign(.rounded)
                                        }
                                        Slider(
                                            value: Binding(
                                                get: { Double(room.light_night ?? 0) },
                                                set: { room.light_night = Int($0); roomModel.updateRoomDebounced(room) }
                                            ),
                                            in: 0...100, step: 5
                                        ).tint(.indigo)
                                    }
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Image(systemName: "sun.max.fill")
                                                .foregroundColor(.orange)
                                                .symbolColorRenderingMode(.gradient)
                                                .shadow(color: .orange, radius: 10, x: 0, y: 0)
                                                .contentTransition(.symbolEffect(.replace.magic(fallback: .downUp.byLayer)))
                                            Text("Morning: \(room.light_morning ?? 100)%")
                                                .font(.subheadline)
                                                .fontWeight(.bold)
                                                .fontDesign(.rounded)
                                        }
                                        Slider(
                                            value: Binding(
                                                get: { Double(room.light_morning ?? 100) },
                                                set: { room.light_morning = Int($0); roomModel.updateRoomDebounced(room) }
                                            ),
                                            in: 0...100, step: 5
                                        )
                                        .tint(.orange)
                                    }
                                }
                            }
                        }
                    }
                }
                .listStyle(.insetGrouped)
                .refreshable {
                    await refreshData()
                }
            }
        }
        .navigationTitle(room.name)
        .task {
            await refreshData()
        }
    }

    private var unavailableContent: some View {
        ContentUnavailableView(
            "No Sensors",
            systemImage: "sensor",
            description: Text("Sensors are created automatically when a night of sleep data is recorded. Make sure your sleep tracking devices are properly connected and have recorded data for this room.")
        )
    }

    private func refreshData() async {
        guard let roomId = room.id else { return }
        await sensorModel.fetchSensors(for: roomId, houseId: house.id)
    }
}

// MARK: - Sensor Detail View (Chart + Log List)
struct SensorDetailView: View {
    let sensor: Sensor
    @ObservedObject var sensorModel: SensorModel

    private var sType: SensorType {
        sensor.sensorType ?? .ambient_temp
    }

    private var chartPoints: [ChartDataPoint] {
        sensorModel.chartData[sensor.sensorID] ?? []
    }

    private var yAxisBounds: ClosedRange<Double> {
        let values = chartPoints.map(\.value)
        let minVal = values.min() ?? 0
        let maxVal = values.max() ?? 10
        let range = max(maxVal - minVal, 1.0)
        let padding = range * 0.25
        return (minVal - padding)...(maxVal + padding)
    }

    var body: some View {
        List {
            // MARK: - Chart Section
            Section {
                VStack(alignment: .leading, spacing: 16) {
                    // Time range picker
                    Picker("Time Range", selection: $sensorModel.selectedTimeRange) {
                        ForEach(TimeRange.allCases, id: \.self) { range in
                            Text(range.rawValue)
                                .fontDesign(.rounded)
                                .tag(range)
                        }
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: sensorModel.selectedTimeRange) { _, _ in
                        Task { await sensorModel.loadChartData(for: sensor) }
                    }

                    if sensorModel.isChartLoading {
                        HStack {
                            Spacer()
                            ProgressView("Loading chart...")
                            Spacer()
                        }
                        .frame(height: 300)
                    } else if chartPoints.isEmpty {
                        ContentUnavailableView("No Data", systemImage: "chart.xyaxis.line")
                            .frame(maxWidth: .infinity, minHeight: 300)
                    } else {
                        Chart {
                            ForEach(chartPoints) { point in
                                LineMark(
                                    x: .value("Time", point.date),
                                    y: .value("Value", point.value)
                                )
                                .interpolationMethod(.catmullRom)
                                .foregroundStyle(sType.color)

                                AreaMark(
                                    x: .value("Time", point.date),
                                    yStart: .value("Min", yAxisBounds.lowerBound),
                                    yEnd: .value("Value", point.value)
                                )
                                .interpolationMethod(.catmullRom)
                                .foregroundStyle(
                                    LinearGradient(
                                        colors: [sType.color.opacity(0.35), .clear],
                                        startPoint: .top,
                                        endPoint: .bottom
                                    )
                                )
                            }
                        }
                        .chartYScale(domain: yAxisBounds)
                        .chartYAxis {
                            if sType == .vibration {
                                AxisMarks(values: [0.0, 0.1]) { value in
                                    AxisGridLine()
                                    AxisTick()
                                    AxisValueLabel {
                                        if let v = value.as(Double.self) {
                                            Text(v >= 0.05 ? "Detected" : "Undetected")
                                                .fontDesign(.rounded)
                                        }
                                    }
                                }
                            } else if sType == .presence {
                                AxisMarks(values: [0.0, 1.0]) { value in
                                    AxisGridLine()
                                    AxisTick()
                                    AxisValueLabel {
                                        if let v = value.as(Double.self) {
                                            Text(v >= 0.5 ? "Occupied" : "Empty")
                                                .fontDesign(.rounded)
                                        }
                                    }
                                }
                            } else {
                                AxisMarks()
                            }
                        }
                        .chartXAxis {
                            switch sensorModel.selectedTimeRange {
                            case .today:
                                AxisMarks(values: .stride(by: .hour, count: 4)) { value in
                                    AxisGridLine()
                                    AxisTick()
                                    if let d = value.as(Date.self) { AxisValueLabel { Text(d, format: .dateTime.hour(.defaultDigits(amPM: .omitted)).minute())
                                        .fontDesign(.rounded) } }
                                }
                            case .week:
                                AxisMarks(values: .stride(by: .day, count: 1)) { value in
                                    AxisGridLine()
                                    AxisTick()
                                    if let d = value.as(Date.self) { AxisValueLabel { Text(d, format: .dateTime.weekday(.abbreviated))
                                        .fontDesign(.rounded) } }
                                }
                            case .month:
                                AxisMarks(values: .stride(by: .day, count: 7)) { value in
                                    AxisGridLine()
                                    AxisTick()
                                    if let d = value.as(Date.self) { AxisValueLabel { Text(d, format: .dateTime.day().month(.abbreviated))
                                        .fontDesign(.rounded) } }
                                }
                            case .year, .all:
                                AxisMarks(values: .stride(by: .month, count: 3)) { value in
                                    AxisGridLine()
                                    AxisTick()
                                    if let d = value.as(Date.self) { AxisValueLabel { Text(d, format: .dateTime.month(.abbreviated))
                                        .fontDesign(.rounded) } }
                                }
                            }
                        }
                        .chartYAxisLabel(sType.yAxisLabel, alignment: .trailing)
                        .frame(height: 300)
                        .padding(.top, 8)
                        .animation(.easeInOut(duration: 0.4), value: chartPoints.map(\.id))
                    }
                }
                .padding(.vertical, 8)
            }

            // MARK: - Data Log Section
            Section(header: logHeader) {
                if chartPoints.isEmpty {
                    ContentUnavailableView(
                        "No Data",
                        systemImage: "list.bullet",
                        description: Text("No logs recorded yet.")
                    )
                    .frame(maxWidth: .infinity, minHeight: 180)
                } else {
                    ForEach(chartPoints.reversed()) { point in
                        HStack {
                            Text(formatLogDate(point.date))
                                .font(.subheadline)
                                .fontDesign(.rounded)
                                .foregroundColor(.secondary)
                                .contentTransition(.numericText(value: point.date.timeIntervalSince1970))
                                .animation(.snappy, value: point.date)

                            Spacer()
                            
                            Text(sType.formatValue(point.value))
                                .fontWeight(.bold)
                                .fontDesign(.rounded)
                                .foregroundColor(.primary)
                                .contentTransition(.numericText(value: point.value))
                                .animation(.snappy, value: point.value)
                        }
                        .padding(.vertical, 2)
                    }
                }
            }
        }
        // navigation title includes icon + sensor name
        .navigationTitle("\(sType.label)")
        .refreshable {
            await sensorModel.loadChartData(for: sensor)
        }
        .task {
            await sensorModel.loadChartData(for: sensor)
        }
    }

    // MARK: - Log Header
    private var logHeader: some View {
        HStack {
            Text("\(chartPoints.count) records")
                .fontDesign(.rounded)
                .contentTransition(.numericText(value: Double(chartPoints.count)))
            Spacer()
            Text("Avg: \(sType.formatValue(averageValue))")
                .font(.caption)
                .fontDesign(.rounded)
                .textCase(.none)
                .contentTransition(.numericText(value: averageValue))
        }
        .animation(.snappy, value: sensorModel.selectedTimeRange)
        .animation(.snappy, value: chartPoints.count)
    }

    // MARK: - Average
    private var averageValue: Double {
        guard !chartPoints.isEmpty else { return 0 }
        return chartPoints.map(\.value).reduce(0, +) / Double(chartPoints.count)
    }

    // MARK: - Date Formatters
    private func formatLogDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        switch sensorModel.selectedTimeRange {
        case .today:
            formatter.doesRelativeDateFormatting = true
            formatter.dateStyle = .medium
            formatter.timeStyle = .short
        case .year, .all:
            formatter.dateFormat = "MMMM yyyy"
        default:
            formatter.doesRelativeDateFormatting = true
            formatter.dateStyle = .medium
            formatter.timeStyle = .none
        }
        return formatter.string(from: date)
    }
}
