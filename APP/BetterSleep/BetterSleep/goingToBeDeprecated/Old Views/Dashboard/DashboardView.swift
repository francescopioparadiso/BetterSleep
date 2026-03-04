//import SwiftUI
//import Combine
//import Foundation
//
//struct DashboardView: View {
//    @StateObject private var viewModel = DashboardViewModel()
//    
//    // Grid layout for our 5 metric cards
//    let columns = [
//        GridItem(.flexible()),
//        GridItem(.flexible())
//    ]
//    
//    var body: some View {
//        NavigationView {
//            ScrollView {
//                VStack(spacing: 25) {
//                    
//                    // --- 1. DATE NAVIGATOR ---
//                    HStack {
//                        Button(action: { viewModel.changeDate(by: -1) }) {
//                            Image(systemName: "chevron.left.circle.fill")
//                                .font(.title)
//                                .foregroundColor(viewModel.isLoading ? .gray : .blue)
//                        }
//                        .disabled(viewModel.isLoading)
//                        
//                        Spacer()
//                        
//                        Text(formatHeaderDate(viewModel.targetDate))
//                            .font(.title2)
//                            .bold()
//                            .foregroundColor(.primary)
//                        
//                        Spacer()
//                        
//                        Button(action: { viewModel.changeDate(by: 1) }) {
//                            Image(systemName: "chevron.right.circle.fill")
//                                .font(.title)
//                                .foregroundColor(viewModel.isToday || viewModel.isLoading ? .gray.opacity(0.3) : .blue)
//                        }
//                        .disabled(viewModel.isToday || viewModel.isLoading)
//                    }
//                    .padding(.horizontal, 25)
//                    .padding(.top, 10)
//                    
//                    // --- 2. DASHBOARD CONTENT ---
//                    if viewModel.isLoading && viewModel.sleepSegments.isEmpty {
//                        ProgressView("Analyzing...")
//                            .frame(maxWidth: .infinity, minHeight: 300)
//                    } else if viewModel.sleepSegments.isEmpty {
//                        ContentUnavailableView(
//                            "No Sleep Data",
//                            systemImage: "moon.zzz",
//                            description: Text("No sensor data found for this date.")
//                        )
//                        .frame(minHeight: 300)
//                    } else {
//                        SleepScoreGauge(score: viewModel.sleepScore)
//                            .padding(.top, -10)
//                        
//                        // NEW: 2-Column Grid for Metrics
//                        LazyVGrid(columns: columns, spacing: 15) {
//                            MetricCard(title: "In Bed", value: viewModel.totalTimeInBed, icon: "bed.double.fill", color: .blue)
//                            MetricCard(title: "Deep Sleep", value: viewModel.deepSleepTime, icon: "moon.stars.fill", color: .indigo)
//                            MetricCard(title: "Avg HR", value: viewModel.avgHeartRate, icon: "heart.fill", color: .red)
//                            MetricCard(title: "Resting HR", value: viewModel.rhr, icon: "heart.circle.fill", color: .orange)
//                            MetricCard(title: "HRV (Est.)", value: viewModel.hrv, icon: "waveform.path.ecg", color: .purple)
//                        }
//                        .padding(.horizontal)
//                        
//                        SleepStageChart(
//                            segments: viewModel.sleepSegments,
//                            bedtime: viewModel.chartBedtime,
//                            wakeTime: viewModel.chartWakeTime
//                        )
//                        .padding(.horizontal)
//                    }
//                }
//            }
//            .navigationTitle("Sleep Dashboard")
//            .background(Color(.systemGroupedBackground))
//            .refreshable {
//                await viewModel.fetchLatestSleepData()
//            }
//            .task {
//                await viewModel.fetchLatestSleepData()
//            }
//        }
//    }
//    
//    // MARK: - Date Formatter
//    private func formatHeaderDate(_ date: Date) -> String {
//        let calendar = Calendar.current
//        if calendar.isDateInToday(date) {
//            return "Today"
//        } else if calendar.isDateInYesterday(date) {
//            return "Yesterday"
//        } else {
//            let formatter = DateFormatter()
//            formatter.dateFormat = "EEE, MMM d"
//            return formatter.string(from: date)
//        }
//    }
//}
