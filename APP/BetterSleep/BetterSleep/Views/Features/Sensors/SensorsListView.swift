import SwiftUI

struct SensorsListView: View {
    var room: Room
    @StateObject private var viewModel = SensorViewModel()
    
    @State private var showingAddSensor = false
    @State private var newSensorName = ""
    @State private var newSensorType: SensorType = .temperature // Now defaults using Enum
    
    // Dynamically calculate which sensors aren't in the room yet using the Enum
    var availableTypes: [SensorType] {
        let usedTypes = Set(viewModel.sensors.map { $0.sensor_type })
        return SensorType.allCases.filter { !usedTypes.contains($0) }
    }
    
    var body: some View {
        Group {
            if viewModel.isLoading {
                ProgressView("Loading sensors...")
            } else if viewModel.sensors.isEmpty {
                ContentUnavailableView(
                    "No Sensors",
                    systemImage: "sensor",
                    description: Text("Tap + to add a thermostat, light, humidity, or passive sensor.")
                )
            } else {
                List {
                    ForEach($viewModel.sensors) { $sensor in
                        Section {
                            // ROW 1: Header
                            NavigationLink(destination: SensorDetailView(sensor: sensor)) {
                                Label(
                                    sensor.name,
                                    systemImage: sensor.sensor_type.icon
                                )
                                .font(.headline)
                                .foregroundColor(sensor.sensor_type.color)
                            }
                            
                            // ROW 2: Controls
                            if sensor.sensor_type.isPassive {
                                HStack {
                                    Text(sensor.sensor_type.passiveDescription)
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                    Spacer()
                                    HStack(spacing: 6) {
                                        Circle().fill(Color.green).frame(width: 8, height: 8)
                                        Text("Monitoring").font(.caption).bold().foregroundColor(.green)
                                    }
                                    .padding(.horizontal, 8).padding(.vertical, 4)
                                    .background(Color.green.opacity(0.15)).cornerRadius(8)
                                }
                            } else {
                                VStack(alignment: .leading, spacing: 16) {
                                    // Bedtime Target
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Image(systemName: "moon.stars.fill").foregroundColor(.indigo)
                                            Text("Bedtime Target: \(sensor.sensor_type.formatValue(sensor.bedtime_value))")
                                                .font(.subheadline).bold()
                                        }
                                        Slider(value: $sensor.bedtime_value, in: sensor.sensor_type.bounds, step: sensor.sensor_type.step)
                                            .tint(.indigo)
                                            .onChange(of: sensor.bedtime_value) { _, _ in viewModel.updateSensorDebounced(sensor: sensor) }
                                    }
                                    
                                    // Wakeup Target
                                    VStack(alignment: .leading, spacing: 4) {
                                        HStack {
                                            Image(systemName: "sun.max.fill").foregroundColor(.orange)
                                            Text("Wakeup Target: \(sensor.sensor_type.formatValue(sensor.wakeup_value))")
                                                .font(.subheadline).bold()
                                        }
                                        Slider(value: $sensor.wakeup_value, in: sensor.sensor_type.bounds, step: sensor.sensor_type.step)
                                            .tint(.orange)
                                            .onChange(of: sensor.wakeup_value) { _, _ in viewModel.updateSensorDebounced(sensor: sensor) }
                                    }
                                }
                            }
                        }
                    }
                    .onDelete { indexSet in Task { await viewModel.deleteSensor(at: indexSet) } }
                }
                .listStyle(.insetGrouped)
            }
        }
        .navigationTitle(room.name)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                if !availableTypes.isEmpty {
                    Button(action: {
                        if let firstAvailable = availableTypes.first {
                            newSensorType = firstAvailable
                        }
                        showingAddSensor = true
                    }) {
                        Image(systemName: "plus")
                    }
                }
            }
        }
        .sheet(isPresented: $showingAddSensor) {
            NavigationView {
                Form {
                    Section(header: Text("Sensor Details")) {
                        TextField("Sensor Name (e.g. Bed Sensor)", text: $newSensorName)
                        
                        Picker("Sensor Type", selection: $newSensorType) {
                            ForEach(availableTypes, id: \.self) { type in
                                Text(type.label).tag(type) // Automatically pulls labels!
                            }
                        }.pickerStyle(.menu)
                    }
                }
                .navigationTitle("Add Sensor")
                .navigationBarTitleDisplayMode(.inline)
//                .toolbar {
//                    ToolbarItem(placement: .navigationBarLeading) { Button("Cancel") { showingAddSensor = false } }
//                    ToolbarItem(placement: .navigationBarTrailing) {
//                        Button("Add") {
//                            Task {
//                                let finalName = newSensorName.isEmpty ? "New Sensor" : newSensorName
//                                if let rid = room.id { await viewModel.addSensor(name: finalName, type: newSensorType, roomId: rid) }
//                                newSensorName = ""; showingAddSensor = false
//                            }
//                        }.bold()
//                    }
//                }
            }
            .presentationDetents([.medium])
        }
//        .task { if let rid = room.id { await viewModel.fetchSensors(roomId: rid) } }
    }
}
