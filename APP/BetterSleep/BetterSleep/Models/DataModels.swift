import Foundation
import SwiftUI

// MARK: - Sensor Type Enum
enum SensorType: String, Codable, CaseIterable, Hashable {
    case temperature = "temperature"
    case humidity = "humidity"
    case light = "light"
    case hr = "hr"
    case presence = "presence"
    
    var label: String {
        switch self {
        case .temperature: return "Temperature"
        case .humidity: return "Humidity"
        case .light: return "Light"
        case .hr: return "Heart Rate"
        case .presence: return "Presence"
        }
    }
    
    var icon: String {
        switch self {
        case .temperature: return "thermometer"
        case .humidity: return "drop.degreesign.fill"
        case .light: return "lightbulb.max.fill"
        case .hr: return "heart.fill"
        case .presence: return "bed.double.fill"
        }
    }
    
    var color: Color {
        switch self {
        case .temperature: return .orange
        case .humidity: return .cyan
        case .light: return .yellow
        case .hr: return .red
        case .presence: return .indigo
        }
    }
    
    var yAxisLabel: String {
        switch self {
        case .temperature: return "Temperature (°C)"
        case .humidity: return "Humidity (%)"
        case .light: return "Light Level (%)"
        case .hr: return "Heart Rate (bpm)"
        case .presence: return "Occupancy Level"
        }
    }
    
    func formatValue(_ value: Double) -> String {
        switch self {
        case .temperature: return String(format: "%.1f°C", value)
        case .humidity, .light: return String(format: "%.0f%%", value)
        case .hr: return String(format: "%.0f bpm", value)
        case .presence: return value >= 0.5 ? "Occupied" : "Empty"
        }
    }
    
    var passiveDescription: String {
        switch self {
        case .hr: return "Records HR while in bed"
        case .presence: return "Detects bed occupancy"
        default: return ""
        }
    }
    
    var bounds: ClosedRange<Double> {
        self == .temperature ? 15.0...30.0 : 0.0...100.0
    }
    
    var step: Double {
        self == .temperature ? 0.5 : 5.0
    }
    
    var isPassive: Bool {
        self == .hr || self == .presence
    }
    
    var defaultBedtime: Double {
        switch self {
        case .temperature: return 18.5
        case .humidity: return 50.0
        case .light: return 0.0
        case .hr, .presence: return 1.0
        }
    }
    
    var defaultWakeup: Double {
        switch self {
        case .temperature: return 21.0
        case .humidity: return 50.0
        case .light: return 100.0
        case .hr, .presence: return 1.0
        }
    }
}

// MARK: - Updated Postgres Models (IDs are now Int)

struct User: Identifiable, Codable, Hashable {
    var id: Int
    var email: String
    var night_time: String?
    var morning_time: String?
    var created_at: String?
}

struct House: Codable, Identifiable, Hashable {
    var id: Int?
    var name: String
    var created_at: String?
}

struct Room: Identifiable, Codable, Hashable {
    var id: Int?
    var house_id: Int
    var name: String
    var user_id: Int?
    var bedtime: String?
    var wake_time: String?
    var desired_temperature: Int?
    var created_at: String?
}

struct Sensor: Codable, Identifiable, Hashable {
    var id: Int?
    var room_id: Int
    var name: String
    var sensor_type: SensorType
    var bedtime_value: Double
    var wakeup_value: Double
}

struct SensorDataLog: Identifiable, Codable, Hashable {
    var id: Int?
    var sensor_id: Int
    var value: Double
    var created_at: String
}

struct Invitation: Codable, Identifiable {
    var id: Int?
    var house_id: Int
    var email: String
    var status: Int? // 0: pending, 1: accepted, 2: rejected
    var created_at: String?
}

struct HouseMember: Identifiable, Codable, Hashable {
    var id: Int?
    var house_id: Int
    var user_id: Int
    var role: Int? // 0: owner/admin, 1: member
    var email: String? // Manually populated via Swift
}
