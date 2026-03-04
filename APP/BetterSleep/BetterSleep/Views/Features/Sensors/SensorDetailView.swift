import SwiftUI
import Supabase
import Charts
import Combine
import Foundation

// MARK: - Enums & Structs
enum TimeRange: String, CaseIterable {
    case today = "1D"
    case week = "1W"
    case month = "1M"
    case year = "1Y"
    case allTime = "All"
}

struct ChartDataPoint: Identifiable {
    let id = UUID()
    let date: Date
    let value: Double
}

// MARK: - View Model
@MainActor
class SensorDetailViewModel: ObservableObject {
    @Published var logs: [SensorDataLog] = []
    @Published var chartData: [ChartDataPoint] = []
    
    @Published var isLoadingLogs = false
    @Published var isChartLoading = false
    @Published var totalCount: Int = 0
    
    @Published var selectedTimeRange: TimeRange = .today
    
    // Pagination State
    @Published var isFetchingMore = false
    @Published var hasMoreData = true
    private var currentPage = 0
    private let pageSize = 100
    
    func refreshAll(sensorId: UUID) async {
        await fetchTotalCount(sensorId: sensorId)
        await fetchChartData(sensorId: sensorId)
        currentPage = 0
        hasMoreData = true
        logs = []
        await fetchLogs(sensorId: sensorId)
    }
    
    func fetchInitialData(sensorId: UUID) async {
        isLoadingLogs = true
        await refreshAll(sensorId: sensorId)
        isLoadingLogs = false
    }
    
    private func fetchTotalCount(sensorId: UUID) async {
        do {
            let response = try await supabase
                .from("sensor_data")
                .select(head: true, count: .exact)
                .eq("sensor_id", value: sensorId)
                .execute()
            self.totalCount = response.count ?? 0
        } catch { print("❌ Error fetching count: \(error)") }
    }
    
    func fetchLogs(sensorId: UUID) async {
        guard hasMoreData else { return }
        if currentPage > 0 { isFetchingMore = true }
        
        let fromIndex = currentPage * pageSize
        let toIndex = fromIndex + pageSize - 1
        
        do {
            let newLogs: [SensorDataLog] = try await supabase
                .from("sensor_data")
                .select()
                .eq("sensor_id", value: sensorId)
                .order("created_at", ascending: false)
                .range(from: fromIndex, to: toIndex)
                .execute()
                .value
            
            if newLogs.count < pageSize { hasMoreData = false }
            self.logs.append(contentsOf: newLogs)
            self.currentPage += 1
        } catch { print("❌ Error fetching logs: \(error)") }
        isFetchingMore = false
    }
    
    func fetchChartData(sensorId: UUID) async {
        isChartLoading = true
        let now = Date()
        let calendar = Calendar.current
        var startDate: Date?
        
        switch selectedTimeRange {
        case .today: startDate = calendar.startOfDay(for: now)
        case .week: startDate = calendar.date(byAdding: .day, value: -7, to: now)
        case .month: startDate = calendar.date(byAdding: .month, value: -1, to: now)
        case .year: startDate = calendar.date(byAdding: .year, value: -1, to: now)
        case .allTime: startDate = nil
        }
        
        do {
            var query = supabase
                .from("sensor_data")
                .select()
                .eq("sensor_id", value: sensorId)
            
            if let start = startDate {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                let startString = formatter.string(from: start)
                query = query.gte("created_at", value: startString)
            }
            
            let rawLogs: [SensorDataLog] = try await query
                .limit(100000)
                .execute()
                .value
            
            self.chartData = aggregate(logs: rawLogs, range: selectedTimeRange)
        } catch { print("❌ Error fetching chart data: \(error)") }
        isChartLoading = false
    }
    
    private func aggregate(logs: [SensorDataLog], range: TimeRange) -> [ChartDataPoint] {
        let calendar = Calendar.current
        let grouped = Dictionary(grouping: logs) { log -> Date in
            guard let date = parseDate(log.created_at) else { return Date() }
            switch range {
            case .today:
                let components = calendar.dateComponents([.year, .month, .day, .hour], from: date)
                return calendar.date(from: components) ?? date
            case .week, .month:
                return calendar.startOfDay(for: date)
            case .year:
                let components = calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: date)
                return calendar.date(from: components) ?? date
            case .allTime:
                let components = calendar.dateComponents([.year, .month], from: date)
                return calendar.date(from: components) ?? date
            }
        }
        
        var aggregated: [ChartDataPoint] = []
        for (date, bucketLogs) in grouped {
            let sum = bucketLogs.reduce(0) { $0 + $1.value }
            let avg = sum / Double(bucketLogs.count)
            aggregated.append(ChartDataPoint(date: date, value: avg))
        }
        return aggregated.sorted { $0.date < $1.date }
    }
    
    private func parseDate(_ dateString: String) -> Date? {
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = isoFormatter.date(from: dateString) { return d }
        let backupFormatter = ISO8601DateFormatter()
        return backupFormatter.date(from: dateString)
    }
}

// MARK: - Views
struct SensorDetailView: View {
    var sensor: Sensor
    @StateObject private var viewModel = SensorDetailViewModel()
    
    var yAxisBoundaries: ClosedRange<Double> {
        let minVal = viewModel.chartData.map { $0.value }.min() ?? 0
        let maxVal = viewModel.chartData.map { $0.value }.max() ?? 10
        let range = max(maxVal - minVal, 1.0)
        let padding = range * 0.2
        return (minVal - padding)...(maxVal + padding)
    }
    
    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 16) {
                    Picker("Time Range", selection: $viewModel.selectedTimeRange) {
                        ForEach(TimeRange.allCases, id: \.self) { range in
                            Text(range.rawValue).tag(range)
                        }
                    }
                    .pickerStyle(.segmented)
//                    .onChange(of: viewModel.selectedTimeRange) { _, _ in
//                        Task { if let sid = sensor.id { await viewModel.fetchChartData(sensorId: sid) } }
//                    }
                    
                    if viewModel.isChartLoading {
                        HStack { Spacer(); ProgressView("Loading chart..."); Spacer() }.frame(height: 300)
                    } else if viewModel.chartData.isEmpty {
                        ContentUnavailableView("No Data", systemImage: "chart.xyaxis.line").frame(height: 300)
                    } else {
                        Chart {
                            ForEach(viewModel.chartData) { point in
                                LineMark(x: .value("Time", point.date), y: .value("Average", point.value))
                                    .interpolationMethod(.catmullRom)
                                    .foregroundStyle(sensor.sensor_type.color) // Used Enum!
                                
                                PointMark(x: .value("Time", point.date), y: .value("Average", point.value))
                                    .foregroundStyle(sensor.sensor_type.color) // Used Enum!
                                
                                AreaMark(x: .value("Time", point.date), yStart: .value("Min", yAxisBoundaries.lowerBound), yEnd: .value("Average", point.value))
                                    .interpolationMethod(.catmullRom)
                                    .foregroundStyle(
                                        LinearGradient(
                                            colors: [sensor.sensor_type.color.opacity(0.4), .clear], // Used Enum!
                                            startPoint: .top, endPoint: .bottom
                                        )
                                    )
                            }
                        }
                        .chartYScale(domain: yAxisBoundaries)
                        .chartXAxis {
                            AxisMarks(values: .automatic(desiredCount: 7)) { value in
                                AxisGridLine(); AxisTick()
                                let date = value.as(Date.self) ?? Date()
                                AxisValueLabel(multiLabelAlignment: .top) {
                                    Text(self.formatAxisDate(date, range: viewModel.selectedTimeRange))
                                        .font(.caption2).fixedSize()
                                        .rotationEffect(.degrees(viewModel.selectedTimeRange == .today ? 0 : -90))
                                        .frame(width: viewModel.selectedTimeRange == .today ? nil : 20, height: viewModel.selectedTimeRange == .today ? nil : 55)
                                        .padding(.top, viewModel.selectedTimeRange == .today ? 0 : 8)
                                }
                            }
                        }
                        .chartXAxisLabel("Time", alignment: .center)
                        .chartYAxisLabel(sensor.sensor_type.yAxisLabel, alignment: .trailing) // Used Enum!
                        .frame(height: 350)
                        .padding(.top, 10)
                    }
                }
                .padding(.vertical, 8)
            }
            .listRowBackground(Color(.systemGroupedBackground))
            .listRowInsets(EdgeInsets(top: 0, leading: 0, bottom: 0, trailing: 0))
            
            Section(header: headerView) {
                if viewModel.isLoadingLogs && viewModel.logs.isEmpty {
                    HStack { Spacer(); ProgressView("Loading logs..."); Spacer() }.listRowBackground(Color.clear)
                } else if viewModel.logs.isEmpty {
                    ContentUnavailableView("No Data", systemImage: "list.bullet", description: Text("No logs recorded yet."))
                } else {
                    ForEach(viewModel.logs) { log in
                        HStack {
                            Text(formatDateString(log.created_at))
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                            Spacer()
                            Text(sensor.sensor_type.formatValue(log.value)) // Used Enum!
                                .bold()
                                .foregroundColor(.primary)
                        }
                        .padding(.vertical, 2)
//                        .onAppear {
//                            if log == viewModel.logs.last { Task { if let sid = sensor.id { await viewModel.fetchLogs(sensorId: sid) } } }
//                        }
                    }
                    if viewModel.isFetchingMore {
                        HStack { Spacer(); ProgressView(); Spacer() }.listRowBackground(Color.clear)
                    }
                }
            }
        }
        .navigationTitle("Logs")
//        .refreshable { if let sid = sensor.id { await viewModel.refreshAll(sensorId: sid) } }
//        .task { if let sid = sensor.id { await viewModel.fetchInitialData(sensorId: sid) } }
    }
    
    private var headerView: some View {
        HStack {
            Image(systemName: sensor.sensor_type.icon) // Used Enum!
            Text(sensor.name)
            Spacer()
            Text("\(viewModel.totalCount) records").font(.caption).textCase(.none)
        }
    }
    
    // MARK: - Formatters
    private func formatDateString(_ dateString: String) -> String {
        let isoFormatter = ISO8601DateFormatter()
        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = isoFormatter.date(from: dateString)
        if date == nil {
            let backupFormatter = ISO8601DateFormatter()
            date = backupFormatter.date(from: dateString)
        }
        guard let validDate = date else { return dateString }
        let displayFormatter = DateFormatter()
        displayFormatter.dateStyle = .medium
        displayFormatter.timeStyle = .medium
        displayFormatter.doesRelativeDateFormatting = true
        return displayFormatter.string(from: validDate)
    }
    
    private func formatAxisDate(_ date: Date, range: TimeRange) -> String {
        let formatter = DateFormatter()
        switch range {
        case .today: formatter.dateFormat = "HH:mm"
        case .week: formatter.dateFormat = "EEE d"
        case .month: formatter.dateFormat = "MMM d"
        case .year: formatter.dateFormat = "MMM yyyy"
        case .allTime: formatter.dateFormat = "MMM yyyy"
        }
        return formatter.string(from: date)
    }
}
