"""
device_connector/Simulate_Sensor.py
Simulates sensors and actuators for BetterSleep IoT project.
"""

# -------------------- IMPORTS --------------------
import threading
import time
import json
import random
import logging

from models import Sensor

# -------------------- LOGGING SETUP --------------------
logging.basicConfig(level=logging.INFO)

# -------------------- CONFIG GENERATOR --------------------
def create_config(
    catalog_url,
    comp_id,
    name,
    comp_type,
    house_id,
    room_id,
    broker,
    port,
    topic_subscribe=None,
    topic_publish=None,
    is_sensor=True,
    client_id=None
):
    """Create configuration dictionary for a sensor or actuator."""
    id_key = "sensorID" if is_sensor else "ActuatorID"
    return {
        "catalogURL": catalog_url,
        "removeInterval": 30,
        "serviceInfo": {
            id_key: int(comp_id),
            "name": name,
            "type": comp_type,
            "houseID": house_id,
            "roomID": room_id,
            "host": "localhost",
            "port": 0,
        },
        "MQTT": {
            "broker": broker,
            "port": port,
            "topic_subscribe": topic_subscribe,
            "topic_publish": topic_publish,
            "clientID": client_id
        }
    }

# -------------------- SENSOR CLASSES --------------------
class PresenceSensor(Sensor):
    """Simulates a presence sensor."""
    def __init__(self, config):
        super().__init__(config, 2)
    def run(self):
        while True:
            val = random.choice([0, 1])
            self.publish_data(val)
            time.sleep(15)

class TemperatureSensor(Sensor):
    """Simulates a body temperature sensor."""
    def __init__(self, config):
        super().__init__(config, 0)
    def run(self):
        while True:
            val = round(random.uniform(36.0, 37.5), 1)
            self.publish_data(val, unit="°C")
            time.sleep(10)

class HeartRateSensor(Sensor):
    """Simulates a heart rate sensor with sleep cycle monitoring."""
    def __init__(self, config):
        self.sensor_type = 3
        super().__init__(config, 3)
        self.is_sleeping = False
    def notify(self, topic, payload):
        try:
            data = json.loads(payload)
            action = data.get("action")
            if action == "START_SLEEPING":
                self.is_sleeping = True
                print("\n[HR SENSOR] Starting Sleep Cycle Monitoring...\n")
            elif action == "STOP_SLEEPING":
                self.is_sleeping = False
                print("\n[HR SENSOR] Stopping Monitoring.\n")
        except Exception as e:
            print("Invalid command", e)
    def run(self):
        while True:
            if self.is_sleeping:
                val = random.randint(55, 75)
                self.publish_data(val, unit="bpm")
            time.sleep(5)

class VibrationSensor(Sensor):
    """Simulates a vibration sensor."""
    def __init__(self, config):
        super().__init__(config, 4)
    def run(self):
        while True:
            val = random.randint(0, 10)
            self.publish_data(val)
            time.sleep(10)

# -------------------- MAIN LOGIC --------------------
if __name__ == "__main__":
    CATALOG_URL = "http://127.0.0.1:8080"
    BROKER_IP = "broker.hivemq.com"
    PORT = 1883
    HOUSE = "1"
    ROOM = "1"
    # Topic templates (resolved automatically by BaseIoTComponent)
    PUB_TEMPLATE = "House/{houseID}/Bedroom/{roomID}/sensor/{sensorID}/{type}/data"
    HR_SUB_TOPIC = "House/{houseID}/Bedroom/{roomID}/heart_rate"
    # Configurations
    c_pres = create_config(
        CATALOG_URL, "1", "Presence", "presence", HOUSE, ROOM, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )
    c_hr = create_config(
        CATALOG_URL, "2", "HeartRate", "heart_rate", HOUSE, ROOM, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE, topic_subscribe=HR_SUB_TOPIC
    )
    c_temp = create_config(
        CATALOG_URL, "3", "Temp", "body_temperature", HOUSE, ROOM, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )
    c_vib = create_config(
        CATALOG_URL, "4", "Vibration", "vibration", HOUSE, ROOM, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )
    # Device instances
    presence = PresenceSensor(c_pres)
    heart_rate = HeartRateSensor(c_hr)
    body_temp = TemperatureSensor(c_temp)
    vibration = VibrationSensor(c_vib)
    devices = [presence, heart_rate, body_temp, vibration]
    # Start threads
    for d in devices:
        threading.Thread(target=d.run, daemon=True).start()
    print(f"\n--- House {HOUSE} Room {ROOM} Simulation Active ---\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:

        print("\nShutting down devices...\n")

        for d in devices:
            d.stop()