import threading
import time
import json
from models import Sensor, Actuator

# SENSORS

class PresenceSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            val = input(f"[{self.comp_id}] Enter Presence (1=In Bed, 0=Empty): ")
            self.publish_data(val)

class HeartRateSensor(Sensor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_user_present = False
        # The topic to listen for presence
        self.presence_topic = f"House/{self.house_id}/Bedroom/{self.bedroom_id}/sensor/+/data/presence"

    def on_presence_update(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        self.is_user_present = (str(data['value']) == "1")

    def run(self):
        self.connect_mqtt()
        # Subscribe to presence updates to know if someone is in bed
        self.client.subscribe(self.presence_topic)
        self.client.on_message = self.on_presence_update
        
        while True:
            val = input(f"[{self.comp_id}] Enter Heart Rate: ")
            if self.is_user_present:
                self.publish_data(val)
            else:
                print(">>> Heart Rate NOT published: User is not in bed.")

class VibrationSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            val = input(f"[{self.comp_id}] Enter Vibration Level: ")
            self.publish_data(val)

# ACTUATORS 

class SmartLight(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n[ACTUATOR - LIGHT] Setting brightness to: {data['value']}\n")

class Fan(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n[ACTUATOR - FAN] Status changed to: {data['value']}\n")

class Heater(Actuator):
    def on_message(self, client, userdata, msg):
        import json
        data = json.loads(msg.payload.decode())
        print(f"\n[ACTUATOR - HEATER] Status changed to: {data['value']}\n")

# MAIN EXECUTION

if __name__ == "__main__":
    CATALOG_URL = "http://127.0.0.1:8080" # Change to your actual Catalog IP
    BROKER_IP = "broker.hivemq.com"     # Change to your actual Broker IP
    H_ID, B_ID = "House01", "Bedroom01"

    # Initialize Components
    presence = PresenceSensor(H_ID, B_ID, "PRES_01", "presence", CATALOG_URL, BROKER_IP)
    heart_rate = HeartRateSensor(H_ID, B_ID, "HR_01", "heartrate", CATALOG_URL, BROKER_IP)
    vibration = VibrationSensor(H_ID, B_ID, "VIB_01", "vibration", CATALOG_URL, BROKER_IP)
    
    light = SmartLight(H_ID, B_ID, "LIGHT_01", CATALOG_URL, BROKER_IP)
    fan = Fan(H_ID, B_ID, "FAN_01", CATALOG_URL, BROKER_IP
    heater = Heater(H_ID, B_ID, "HEAT_01", CATALOG_URL, BROKER_IP)

    # Start Actuators
    light.start()
    fan.start()
    heater.start()

    # Start Sensors in separate threads (to use input() simultaneously)
    threading.Thread(target=presence.run, daemon=True).start()
    threading.Thread(target=heart_rate.run, daemon=True).start()
    threading.Thread(target=vibration.run, daemon=True).start()

    print("--- BetterSleep Device Connector Started ---")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
