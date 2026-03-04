//import Foundation
//import Supabase
//import Combine
//
//@MainActor
//class SensorViewModel: ObservableObject {
//    @Published var sensors: [Sensor] = []
//    @Published var isLoading = false
//    private var saveTask: Task<Void, Never>?
//    
//    func fetchSensors(roomId: UUID) async {
//        isLoading = true
//        do {
//            self.sensors = try await supabase
//                .from("sensors")
//                .select()
//                .eq("room_id", value: roomId)
//                .order("created_at", ascending: true)
//                .execute()
//                .value
//        } catch {
//            print("❌ Error fetching sensors: \(error)")
//        }
//        isLoading = false
//    }
//    
//    func addSensor(name: String, type: SensorType, roomId: UUID) async {
////        do {
////            let newSensorId = UUID()
////            let newSensor = Sensor(
////                id: newSensorId,
////                room_id: roomId,
////                name: name,
////                sensor_type: type, // Now uses Enum securely
////                bedtime_value: type.defaultBedtime, // Pulled dynamically from Enum!
////                wakeup_value: type.defaultWakeup    // Pulled dynamically from Enum!
////            )
////            
////            try await supabase
////                .from("sensors")
////                .insert(newSensor)
////                .execute()
////            
////            self.sensors.append(newSensor)
////        } catch {
////            print("❌ Error adding sensor: \(error)")
////        }
//    }
//    
//    func deleteSensor(at offsets: IndexSet) async {
//        for index in offsets {
//            let sensorToDelete = sensors[index]
//            guard let sensorId = sensorToDelete.id else { continue }
//            
//            do {
//                try await supabase
//                    .from("sensors")
//                    .delete()
//                    .eq("id", value: sensorId)
//                    .execute()
//                
//                self.sensors.remove(at: index)
//            } catch {
//                print("❌ Error deleting sensor: \(error)")
//            }
//        }
//    }
//    
//    func updateSensorDebounced(sensor: Sensor) {
//        saveTask?.cancel()
//        saveTask = Task {
//            do {
//                try await Task.sleep(nanoseconds: 1_000_000_000)
//                guard let sid = sensor.id else { return }
//                
//                try await supabase
//                    .from("sensors")
//                    .update(sensor)
//                    .eq("id", value: sid)
//                    .execute()
//                
//                print("✅ Sensor '\(sensor.name)' updated.")
//            } catch is CancellationError {
//                // Expected behavior
//            } catch {
//                print("❌ Error updating sensor: \(error)")
//            }
//        }
//    }
//}
