import SwiftUI
import Charts

enum SleepStage: String, CaseIterable, Identifiable {
    case awake = "Awake"
    case rem = "REM"
    case core = "Core"
    case deep = "Deep"
    
    var id: String { self.rawValue }
    
    // Custom Apple Health-style colors
    var color: Color {
        switch self {
        case .awake: return Color(red: 1.0, green: 0.5, blue: 0.4) // Salmon/Red
        case .rem: return Color(red: 0.4, green: 0.8, blue: 1.0)   // Light Blue
        case .core: return Color(red: 0.2, green: 0.5, blue: 0.9)  // Medium Blue
        case .deep: return Color(red: 0.1, green: 0.2, blue: 0.6)  // Dark Blue
        }
    }
}

struct SleepSegment: Identifiable {
    let id = UUID()
    let startDate: Date
    let endDate: Date
    let stage: SleepStage
}

import SwiftUI
import Charts

struct SleepStageChart: View {
    let segments: [SleepSegment]
    let bedtime: Date
    let wakeTime: Date
    
    // 1. DYNAMIC BOUNDS: Find the earliest and latest data points, compare them to preferences, and add padding.
    var chartStart: Date {
        let earliestData = segments.map { $0.startDate }.min() ?? bedtime
        let baseStart = min(bedtime, earliestData)
        // Add 30 minutes of padding to the left
        return Calendar.current.date(byAdding: .minute, value: -30, to: baseStart)!
    }
    
    var chartEnd: Date {
        let latestData = segments.map { $0.endDate }.max() ?? wakeTime
        let baseEnd = max(wakeTime, latestData)
        // Add 30 minutes of padding to the right
        return Calendar.current.date(byAdding: .minute, value: 30, to: baseEnd)!
    }
    
    // 2. DYNAMIC TICKS: Ensure bedtime, waketime, and every 2 hours in between are labeled
    var axisValues: [Date] {
        var values: [Date] = [bedtime, wakeTime]
        
        var current = Calendar.current.date(bySetting: .minute, value: 0, of: chartStart)!
        while current <= chartEnd {
            if !values.contains(current) { values.append(current) }
            current = Calendar.current.date(byAdding: .hour, value: 2, to: current)!
        }
        
        return Array(Set(values)).sorted()
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Sleep Stages")
                .font(.headline)
                .foregroundColor(.primary)
            
            Chart {
                ForEach(segments) { segment in
                    BarMark(
                        xStart: .value("Start", segment.startDate),
                        xEnd: .value("End", segment.endDate),
                        y: .value("Stage", segment.stage.rawValue)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 4))
                    .foregroundStyle(segment.stage.color)
                }
            }
            .chartYScale(domain: ["Deep", "Core", "REM", "Awake"])
            // USE THE NEW DYNAMIC BOUNDS HERE
            .chartXScale(domain: chartStart...chartEnd)
            .chartYAxis {
                AxisMarks(position: .leading)
            }
            .chartXAxis {
                AxisMarks(values: axisValues) { value in
                    if let date = value.as(Date.self) {
                        let isEdge = date == bedtime || date == wakeTime
                        
                        AxisValueLabel {
                            Text(date, format: .dateTime.hour(.defaultDigits(amPM: .omitted)).minute())
                                .font(isEdge ? .caption.bold() : .caption)
                                .foregroundColor(isEdge ? .primary : .secondary)
                        }
                        AxisGridLine()
                    }
                }
            }
            .frame(height: 220)
        }
        .padding()
        .background(RoundedRectangle(cornerRadius: 16).fill(Color(.secondarySystemGroupedBackground)))
        .shadow(color: .black.opacity(0.05), radius: 10, x: 0, y: 5)
    }
}
