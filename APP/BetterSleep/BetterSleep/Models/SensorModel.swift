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
    @Published var chartData: [Int: [ChartDataPoint]] = [:]
    @Published var isChartLoading = false
    @Published var selectedTimeRange: TimeRange = .today

    private func baseURL() async throws -> String {
        try await CatalogClient.shared.getUserServiceURL()
    }

    // MARK: - Fetch sensors for a room
    func fetchSensors(for roomId: Int) async {
        isLoading = true
        do {
            let base = try await baseURL()
            let url = URL(string: "\(base)/getSensorsByRoom?room_id=\(roomId)")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            let itemData = try JSONSerialization.data(withJSONObject: json?["sensors"] ?? [])
            self.sensors = try JSONDecoder().decode([Sensor].self, from: itemData)
        } catch {
            print("Error fetching sensors: \(error)")
        }
        isLoading = false
    }

    // MARK: - Delete a sensor
    func deleteSensor(sensorId: Int, roomId: Int) async {
        do {
            let base = try await baseURL()
            var req = URLRequest(url: URL(string: "\(base)/removeSensor?id=\(sensorId)")!)
            req.httpMethod = "DELETE"
            _ = try await URLSession.shared.data(for: req)
            self.sensors.removeAll { $0.id == sensorId }
        } catch {
            print("Error deleting sensor: \(error)")
        }
    }

    // MARK: - Generate fake chart data (placeholder until time series DB connected)
    // Generates granular hourly data covering the selected range, then aggregates
    // into averages for wider intervals (daily for week/month, monthly for year).
    func loadFakeChartData(for sensor: Sensor) {
        guard let sensorId = sensor.id else { return }
        isChartLoading = true

        let now = Date()
        let calendar = Calendar.current
        let sensorType = sensor.sensorType ?? .ambient_temp

        // 1. Determine how many hours of raw data to generate
        let totalHours: Int
        switch selectedTimeRange {
        case .today:  totalHours = 24
        case .week:   totalHours = 24 * 7      // 168
        case .month:  totalHours = 24 * 30     // 720
        case .year:   totalHours = 24 * 365    // 8760
        case .all:    totalHours = 24 * 365
        }

        // 2. Generate raw hourly data points
        var rawPoints: [ChartDataPoint] = []
        for i in 0..<totalHours {
            let date = calendar.date(byAdding: .hour, value: -i, to: now) ?? now
            let value = randomValue(for: sensorType)
            rawPoints.append(ChartDataPoint(date: date, value: value))
        }

        // 3. Aggregate if needed
        let finalPoints: [ChartDataPoint]
        switch selectedTimeRange {
        case .today:
            // Show raw hourly points – no aggregation
            finalPoints = rawPoints
        case .week, .month:
            // Aggregate into daily averages
            finalPoints = aggregate(rawPoints, by: .day, calendar: calendar)
        case .year, .all:
            // Aggregate into monthly averages
            finalPoints = aggregate(rawPoints, by: .month, calendar: calendar)
        }

        chartData[sensorId] = finalPoints.sorted { $0.date < $1.date }
        isChartLoading = false
    }

    // MARK: - Helpers

    private func randomValue(for type: SensorType) -> Double {
        switch type {
        case .ambient_temp: return Double.random(in: 17...24)
        case .humidity:     return Double.random(in: 30...70)
        case .light:        return Double.random(in: 0...100)
        case .heart_rate:   return Double.random(in: 55...90)
        case .vibration:    return Double.random(in: 0...5)
        case .presence:     return Double.random(in: 0...1)
        }
    }

    /// Groups raw data points by a calendar component (.day or .month) and
    /// returns one point per bucket whose value is the arithmetic mean.
    private func aggregate(_ points: [ChartDataPoint], by component: Calendar.Component, calendar: Calendar) -> [ChartDataPoint] {
        // Build a dictionary keyed by the start-of-component date
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
