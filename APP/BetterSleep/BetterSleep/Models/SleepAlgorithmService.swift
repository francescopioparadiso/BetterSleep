import Foundation

class SleepAlgorithmService {
//    static let shared = SleepAlgorithmService()
//    
//    /// Entry point: Processes raw logs into a score and a timeline of stages
//    func processSleepData(logs: [SensorDataLog], sensorTypes: [UUID: SensorType]) -> (score: Int, segments: [SleepSegment]) {
//        let sortedLogs = logs.compactMap { log -> (Date, Double, SensorType)? in
//            guard let date = parseDate(log.created_at), let type = sensorTypes[log.sensor_id] else { return nil }
//            return (date, log.value, type)
//        }.sorted { $0.0 < $1.0 }
//        
//        guard !sortedLogs.isEmpty else { return (0, []) }
//        
//        let segments = generateSegments(from: sortedLogs)
//        let score = calculateScore(segments: segments)
//        
//        return (score, segments)
//    }
//    
//    private func generateSegments(from logs: [(Date, Double, SensorType)]) -> [SleepSegment] {
//        var rawEpochs: [(startDate: Date, endDate: Date, stage: SleepStage)] = []
//        let calendar = Calendar.current
//        
//        guard let firstDate = logs.first?.0, let lastDate = logs.last?.0 else { return [] }
//        
//        // STEP 1: Evaluate every 5-minute window
//        var currentStart = firstDate
//        while currentStart < lastDate {
//            let currentEnd = calendar.date(byAdding: .minute, value: 5, to: currentStart)!
//            let windowLogs = logs.filter { $0.0 >= currentStart && $0.0 < currentEnd }
//            
//            let presenceLogs = windowLogs.filter { $0.2 == .presence }
//            let isPresent = presenceLogs.contains { $0.1 >= 0.5 }
//            
//            if isPresent {
//                let hrLogs = windowLogs.filter { $0.2 == .hr }
//                let avgHR = hrLogs.map { $0.1 }.reduce(0, +) / max(Double(hrLogs.count), 1.0)
//                
//                let stage: SleepStage
//                if hrLogs.isEmpty || avgHR > 80 {
//                    stage = .awake
//                } else if avgHR < 55 {
//                    stage = .deep
//                } else if avgHR > 70 {
//                    stage = .rem
//                } else {
//                    stage = .core
//                }
//                rawEpochs.append((currentStart, currentEnd, stage))
//            }
//            currentStart = currentEnd
//        }
//        
//        // STEP 2: MERGE CONTIGUOUS EPOCHS
//        // This stitches matching 5-minute blocks into long, continuous segments for the UI
//        guard !rawEpochs.isEmpty else { return [] }
//        
//        var mergedSegments: [SleepSegment] = []
//        var currentSegmentStart = rawEpochs[0].startDate
//        var currentSegmentEnd = rawEpochs[0].endDate
//        var currentStage = rawEpochs[0].stage
//        
//        for i in 1..<rawEpochs.count {
//            let epoch = rawEpochs[i]
//            
//            // If the stage matches exactly AND the time is contiguous, extend the block!
//            if epoch.stage == currentStage && epoch.startDate == currentSegmentEnd {
//                currentSegmentEnd = epoch.endDate
//            } else {
//                // Otherwise, save the long block and start a new one
//                mergedSegments.append(SleepSegment(startDate: currentSegmentStart, endDate: currentSegmentEnd, stage: currentStage))
//                currentSegmentStart = epoch.startDate
//                currentSegmentEnd = epoch.endDate
//                currentStage = epoch.stage
//            }
//        }
//        // Append the final block
//        mergedSegments.append(SleepSegment(startDate: currentSegmentStart, endDate: currentSegmentEnd, stage: currentStage))
//        
//        return mergedSegments
//    }
//    
//    private func calculateScore(segments: [SleepSegment]) -> Int {
//        var sleepMinutes: Double = 0
//        var awakeInterruptions = 0
//        
//        // Calculate exact durations using the new merged blocks
//        for segment in segments {
//            let duration = segment.endDate.timeIntervalSince(segment.startDate) / 60.0
//            if segment.stage != .awake {
//                sleepMinutes += duration
//            } else {
//                awakeInterruptions += 1
//            }
//        }
//        
//        let durationScore = min(sleepMinutes / 480.0, 1.0) * 70
//        let interruptionPenalty = min(Double(awakeInterruptions) * 2.0, 30.0)
//        
//        return Int(max(durationScore - interruptionPenalty, 0) + 30)
//    }
//    
//    private func parseDate(_ dateString: String) -> Date? {
//        let isoFormatter = ISO8601DateFormatter()
//        isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
//        return isoFormatter.date(from: dateString) ?? ISO8601DateFormatter().date(from: dateString)
//    }
}
