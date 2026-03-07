import Foundation
import SwiftUI
import Combine

// MARK: - Chart Data
struct ChartDataPoint: Identifiable {
    let id = UUID()
    let date: Date
    let value: Double
}

enum TimeRange: String, CaseIterable {
    case today = "1D"
    case week  = "1W"
    case month = "1M"
    case year  = "1Y"
    case all   = "All"
}

// MARK: - Sensor Model
@MainActor
class SensorModel: ObservableObject {
    @Published var sensors: [Sensor] = []
    @Published var isLoading = false

    // Chart data per sensor id
    @Published var chartData: [String: [ChartDataPoint]] = [:]
    @Published var isChartLoading = false
    @Published var selectedTimeRange: TimeRange = .today

    // MARK: - Fetch sensors for a room from the Catalog
    func fetchSensors(for roomId: Int, houseId: Int? = nil) async {
        isLoading = true
        do {
            self.sensors = try await CatalogClient.shared.getSensorsForRoom(roomID: String(roomId))
            // If no sensors found and we have a houseId, activate them first
            if self.sensors.isEmpty, let houseId = houseId {
                try await CatalogClient.shared.activateSensors(roomId: roomId, houseId: houseId)
                self.sensors = try await CatalogClient.shared.getSensorsForRoom(roomID: String(roomId))
            }
        } catch {
            print("Error fetching sensors from catalog: \(error)")
        }
        isLoading = false
    }

    // MARK: - Fetch chart data from TimeSeries DB (SenML)
    func loadChartData(for sensor: Sensor) async {
        isChartLoading = true
        do {
            let tsURL = try await CatalogClient.shared.getTimeSeriesURL()
            guard let roomID = sensor.roomID else {
                print("[ChartData] Sensor \(sensor.sensorID) has no roomID")
                isChartLoading = false
                return
            }
            let sensorTypeCode = sensor.sensorType?.numericCode ?? 0
            let url = URL(string: "\(tsURL)/getSensorByRoomAndType?room_id=\(roomID)&sensor_type=\(sensorTypeCode)")!
            print("[ChartData] Fetching from: \(url.absoluteString)")
            let (data, response) = try await URLSession.shared.data(from: url)
            
            if let httpResponse = response as? HTTPURLResponse {
                print("[ChartData] HTTP Status: \(httpResponse.statusCode)")
                print("[ChartData] Content-Type: \(httpResponse.value(forHTTPHeaderField: "Content-Type") ?? "nil")")
            }
            
            print("[ChartData] Got response (\(data.count) bytes), parsing data...")

            let records = try JSONDecoder().decode([SenMLRecord].self, from: data)
            print("[ChartData] Decoded \(records.count) SenML records")

            var points: [ChartDataPoint] = []
            for record in records {
                for event in record.e {
                    let date = Date(timeIntervalSince1970: event.t)
                    points.append(ChartDataPoint(date: date, value: event.v))
                }
            }

            // Filter by selected time range
            let now = Date()
            let calendar = Calendar.current
            let filteredPoints: [ChartDataPoint]
            switch selectedTimeRange {
            case .today:
                let start = calendar.startOfDay(for: now)
                filteredPoints = points.filter { $0.date >= start }
            case .week:
                let start = calendar.date(byAdding: .day, value: -7, to: now) ?? now
                filteredPoints = points.filter { $0.date >= start }
            case .month:
                let start = calendar.date(byAdding: .month, value: -1, to: now) ?? now
                filteredPoints = points.filter { $0.date >= start }
            case .year:
                let start = calendar.date(byAdding: .year, value: -1, to: now) ?? now
                filteredPoints = points.filter { $0.date >= start }
            case .all:
                filteredPoints = points
            }

            // Aggregate if needed
            let finalPoints: [ChartDataPoint]
            switch selectedTimeRange {
            case .today:
                finalPoints = aggregateEvery10Minutes(filteredPoints, calendar: calendar)
            case .week, .month:
                finalPoints = aggregate(filteredPoints, by: .day, calendar: calendar)
            case .year, .all:
                finalPoints = aggregate(filteredPoints, by: .month, calendar: calendar)
            }

            chartData[sensor.sensorID] = finalPoints.sorted { $0.date < $1.date }
            print("[ChartData] Stored \(finalPoints.count) final points for sensor \(sensor.sensorID)")
        } catch let urlError as URLError {
            print("[ChartData] URLError \(urlError.code.rawValue): \(urlError.localizedDescription)")
            chartData[sensor.sensorID] = []
        } catch {
            print("[ChartData] ERROR loading chart data: \(error)")
            print("[ChartData] Error type: \(type(of: error))")
            chartData[sensor.sensorID] = []
        }
        isChartLoading = false
    }

    // MARK: - Helpers

    private func aggregate(_ points: [ChartDataPoint], by component: Calendar.Component, calendar: Calendar) -> [ChartDataPoint] {
        var buckets: [Date: [Double]] = [:]
        for p in points {
            let key: Date
            switch component {
            case .day:
                key = calendar.startOfDay(for: p.date)
            case .month:
                let comps = calendar.dateComponents([.year, .month], from: p.date)
                key = calendar.date(from: comps) ?? p.date
            default:
                key = p.date
            }
            buckets[key, default: []].append(p.value)
        }
        return buckets.map { date, values in
            let avg = values.reduce(0, +) / Double(values.count)
            return ChartDataPoint(date: date, value: (avg * 10).rounded() / 10)
        }
    }

    private func aggregateEvery10Minutes(_ points: [ChartDataPoint], calendar: Calendar) -> [ChartDataPoint] {
        var buckets: [Date: [Double]] = [:]
        for p in points {
            let comps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: p.date)
            let minute = comps.minute ?? 0
            let roundedMinute = (minute / 10) * 10
            var adjustedComps = comps
            adjustedComps.minute = roundedMinute
            adjustedComps.second = 0
            let key = calendar.date(from: adjustedComps) ?? p.date
            buckets[key, default: []].append(p.value)
        }
        return buckets.map { date, values in
            let avg = values.reduce(0, +) / Double(values.count)
            return ChartDataPoint(date: date, value: (avg * 10).rounded() / 10)
        }
    }
}
