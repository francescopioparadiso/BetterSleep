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
    var active: Bool = false
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

    var numericCode: Int {
        switch self {
        case .ambient_temp: return 0
        case .humidity: return 1
        case .presence: return 2
        case .heart_rate: return 3
        case .vibration: return 4
        case .light: return 5
        }
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

// Sensor as returned by the Catalog service
struct Sensor: Codable, Identifiable, Hashable {
    var sensorID: String
    var name: String
    var endpoint: String?
    var type: String
    var last_update: String?
    var roomID: String?
    var houseID: String?
    var mqtt_topic: String?

    // Identifiable conformance using sensorID
    var id: String { sensorID }

    var sensorType: SensorType? {
        SensorType(rawValue: type)
    }
}

// MARK: - SenML Models (from TimeSeries DB)
struct SenMLEvent: Codable, Hashable {
    var n: String   // name / measurement type
    var u: String   // unit
    var t: Double   // timestamp (unix)
    var v: Double   // value
}

struct SenMLRecord: Codable, Hashable {
    var bn: String       // base name: "houseID:roomID:sensorID:sensorType"
    var e: [SenMLEvent]  // events
}
