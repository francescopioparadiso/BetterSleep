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
    func fetchSensors(for roomId: Int) async {
        isLoading = true
        do {
            self.sensors = try await CatalogClient.shared.getSensorsForRoom(roomID: String(roomId))
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
            let url = URL(string: "\(tsURL)/getSensorById?sensor_id=\(sensor.sensorID)")!
            let (data, _) = try await URLSession.shared.data(from: url)

            let records = try JSONDecoder().decode([SenMLRecord].self, from: data)

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
                finalPoints = filteredPoints
            case .week, .month:
                finalPoints = aggregate(filteredPoints, by: .day, calendar: calendar)
            case .year, .all:
                finalPoints = aggregate(filteredPoints, by: .month, calendar: calendar)
            }

            chartData[sensor.sensorID] = finalPoints.sorted { $0.date < $1.date }
        } catch {
            print("Error loading chart data from TimeSeries: \(error)")
            // If TimeSeries fails, chart stays empty
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
            return ChartDataPoint(date: date, value: avg)
        }
    }
}
