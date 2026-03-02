import SwiftUI

struct SleepScoreGauge: View {
    let score: Int
    
    @State private var minValue: CGFloat = 0.1
    @State private var maxValue: CGFloat = 0.9
    
    
    var body: some View {
        VStack(spacing: -20) {
            ZStack {
                // Background Track
                Circle()
                    .trim(from: minValue, to: maxValue)
                    .stroke(Color.gray.opacity(0.2), style: StrokeStyle(lineWidth: 25, lineCap: .round))
                    .rotationEffect(.degrees(90))
                
                // Active Score Track
                Circle()
                    .trim(from: minValue, to: minValue + (Double(score) / 100.0 * (maxValue - minValue)))
                    .stroke(
                        LinearGradient(colors: [.blue, .cyan], startPoint: .leading, endPoint: .trailing),
                        style: StrokeStyle(lineWidth: 25, lineCap: .round)
                    )
                    .rotationEffect(.degrees(90))
                    .animation(.easeOut(duration: 1.5), value: score)
                
                VStack {
                    Text("\(score)")
                        .font(.system(size: 60, weight: .bold, design: .rounded))
                    Text(scoreLabel)
                        .font(.headline)
                        .foregroundColor(.secondary)
                }
                .offset(y: -10)
            }
            .frame(height: 200)
        }
    }
    
    private var scoreLabel: String {
        if score >= 85 { return "Excellent" }
        if score >= 70 { return "Good" }
        if score >= 50 { return "Fair" }
        return "Poor"
    }
}
