import Foundation
import SwiftUI

// MARK: - Core Postgres Models
struct User: Identifiable, Codable, Hashable {
    var id: Int
    var email: String
}

struct House: Identifiable, Codable, Hashable {
    var id: Int?
    var name: String
    var created_at: String?
}

struct Room: Identifiable, Codable, Hashable {
    var id: Int?
    var house_id: Int
    var name: String
    var user_id: Int?
    var created_at: String?
    var temperature_night: Int?
    var temperature_morning: Int?
    var light_night: Int?
    var light_morning: Int?
}

struct Invitation: Identifiable, Codable, Hashable {
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
    var role: Int? // 0: owner, 1: member
    var email: String? // Manually populated via Swift
}

// MARK: - Sensor Models
enum SensorType: String, Codable, CaseIterable, Hashable {
    case ambient_temp = "ambient_temp"
    case humidity = "humidity"
    case light = "light"
    case heart_rate = "heart_rate"
    case vibration = "vibration"
    case presence = "presence"

    var label: String {
        switch self {
        case .ambient_temp: return "Temperature"
        case .humidity: return "Humidity"
        case .light: return "Light"
        case .heart_rate: return "Heart Rate"
        case .vibration: return "Vibration"
        case .presence: return "Presence"
        }
    }

    var icon: String {
        switch self {
        case .ambient_temp: return "thermometer"
        case .humidity: return "drop.degreesign.fill"
        case .light: return "lightbulb.max.fill"
        case .heart_rate: return "heart.fill"
        case .vibration: return "waveform.path"
        case .presence: return "bed.double.fill"
        }
    }

    var color: Color {
        switch self {
        case .ambient_temp: return .orange
        case .humidity: return .cyan
        case .light: return .yellow
        case .heart_rate: return .red
        case .vibration: return .purple
        case .presence: return .indigo
        }
    }

    var unit: String {
        switch self {
        case .ambient_temp: return "°C"
        case .humidity: return "%"
        case .light: return "%"
        case .heart_rate: return "bpm"
        case .vibration: return ""
        case .presence: return ""
        }
    }

    var yAxisLabel: String {
        switch self {
        case .ambient_temp: return "Temperature (°C)"
        case .humidity: return "Humidity (%)"
        case .light: return "Light Level (%)"
        case .heart_rate: return "Heart Rate (bpm)"
        case .vibration: return "Vibration Level"
        case .presence: return "Occupancy"
        }
    }

    func formatValue(_ value: Double) -> String {
        switch self {
        case .ambient_temp: return String(format: "%.1f°C", value)
        case .humidity, .light: return String(format: "%.0f%%", value)
        case .heart_rate: return String(format: "%.0f bpm", value)
        case .vibration: return String(format: "%.1f", value)
        case .presence: return value >= 0.5 ? "Occupied" : "Empty"
        }
    }

    var isPassive: Bool {
        self == .heart_rate || self == .presence || self == .vibration
    }

    var passiveDescription: String {
        switch self {
        case .heart_rate: return "Records HR while in bed"
        case .presence: return "Detects bed occupancy"
        case .vibration: return "Monitors movement"
        default: return ""
        }
    }
}

struct Sensor: Codable, Identifiable, Hashable {
    var id: Int?
    var room_id: Int
    var type: String
    var name: String
    var mqtt_topic: String?
    var created_at: String?

    var sensorType: SensorType? {
        SensorType(rawValue: type)
    }
}
