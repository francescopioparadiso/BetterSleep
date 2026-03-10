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

from device_connector.models import Sensor, Actuator

# -------------------- LOGGING SETUP --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- CONFIG GENERATOR --------------------
def create_config(
    catalog_url,
    identify,
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
            id_key: str(identify),
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
    """Simulates a presence sensor. In debug mode, only sends values when publish_data is called."""
    def __init__(self, config, debug=False):
        super().__init__(config, 2)
        self.debug = debug
        self._thread = None
        self._stop_event = threading.Event()

    def run(self):
        if not self.debug:
            while not self._stop_event.is_set():
                val = random.choice([0, 1])
                self.publish_data(val)
                time.sleep(15)

    def stop(self):
        self._stop_event.set()
        super().stop()


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
            data=json.loads(payload)
            action = data.get("action")
            if action == "START_SLEEPING":
                self.is_sleeping = True
                logger.info("[HR SENSOR] Starting Sleep Cycle Monitoring...")
            elif action == "STOP_SLEEPING":
                self.is_sleeping = False
                logger.info("[HR SENSOR] Stopping Monitoring.")
        except Exception as e:
            logger.error(f"[HR SENSOR] Error processing command on topic '{topic}': {e}")
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

# -------------------- ACTUATOR CLASSES --------------------
class LightActuator(Actuator):
    """Simulates a light actuator."""
    def __init__(self, config):
        super().__init__(config)
        self.value = 0
        self.timestamp_provider = time.time

    def notify(self, topic, payload):
        try:
            data = json.loads(payload)
            action = data.get("action")
            value = data.get("value")
            if action == "SET" and value is not None:
                next_value = int(value)
                if next_value != self.value:
                    self.value = next_value
                    # Publish state change
                    self.publish_data(self.value, unit="%", name="LightLevel")

            logger.info(f"[LIGHT ACTUATOR] Received command: {action} with value: {value}")
        except Exception as e:
            logger.error(f"[LIGHT ACTUATOR] Error processing command on topic '{topic}': {e}")

class HeaterActuator(Actuator):
    """Simulates a heater actuator."""
    def __init__(self, config):
        super().__init__(config)
        self.state = "OFF"
        self.previous_state = None
        self.timestamp_provider = time.time

    def notify(self, topic, payload):
        try:
            data = json.loads(payload)
            action = data.get("action")
            if action:
                self.state = "ON"
            else:
                self.state = "OFF"

            # Publish state only if it changed
            if self.state != self.previous_state:
                self.previous_state = self.state
                self.publish_data(1 if self.state == "ON" else 0, name="HeaterState")

            logger.info(f"[HEATER ACTUATOR] Received command: {action}, Heater state: {self.state}")
        except Exception as e:
            logger.error(f"[HEATER ACTUATOR] Error processing command on topic '{topic}': {e}")

class FanActuator(Actuator):
    """Simulates a fan actuator."""
    def __init__(self, config):
        super().__init__(config)
        self.state = "OFF"
        self.previous_state = None
        self.timestamp_provider = time.time

    def notify(self, topic, payload):
        try:
            data = json.loads(payload)
            action = data.get("action")
            if action:
                self.state = "ON"
            else:
                self.state = "OFF"

            # Publish state only if it changed
            if self.state != self.previous_state:
                self.previous_state = self.state
                self.publish_data(1 if self.state == "ON" else 0, name="FanState")

            logger.info(f"[FAN ACTUATOR] Received command: {action}, Fan state: {self.state}")
        except Exception as e:
            logger.error(f"[FAN ACTUATOR] Error processing command on topic '{topic}': {e}")

# -------------------- MAIN LOGIC --------------------
if __name__ == "__main__":
    CATALOG_URL = "http://127.0.0.1:8080"
    BROKER_IP = "broker.hivemq.com"
    PORT = 1883
    HOUSE = "1"
    ROOM = "1"
    # Topic templates (resolved automatically by BaseIoTComponent)
    PUB_TEMPLATE = "House/{houseID}/Bedroom/{roomID}/sensor/{type}/{sensorID}/data"
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
    c_light = create_config(
        CATALOG_URL, "5", "Light", "light", HOUSE, ROOM, BROKER_IP, PORT,
        topic_publish="House/{houseID}/Bedroom/{roomID}/actuator/light/data",
        topic_subscribe=f"House/{HOUSE}/Bedroom/{ROOM}/actuator/light/command",
        is_sensor=False
    )
    c_heater = create_config(
        CATALOG_URL, "6", "Heater", "heater", HOUSE, ROOM, BROKER_IP, PORT,
        topic_publish="House/{houseID}/Bedroom/{roomID}/actuator/heater/data",
        topic_subscribe=f"House/{HOUSE}/Bedroom/{ROOM}/actuator/heater/command",
        is_sensor=False
    )
    c_fan = create_config(
        CATALOG_URL, "7", "Fan", "fan", HOUSE, ROOM, BROKER_IP, PORT,
        topic_publish="House/{houseID}/Bedroom/{roomID}/actuator/fan/data",
        topic_subscribe=f"House/{HOUSE}/Bedroom/{ROOM}/actuator/fan/command",
        is_sensor=False
    )
    # Device instances
    presence = PresenceSensor(c_pres)
    heart_rate = HeartRateSensor(c_hr)
    body_temp = TemperatureSensor(c_temp)
    vibration = VibrationSensor(c_vib)
    light_actuator = LightActuator(c_light)
    heater_actuator = HeaterActuator(c_heater)
    fan_actuator = FanActuator(c_fan)
    # Add actuators to devices list
    devices = [presence, heart_rate, body_temp, vibration, light_actuator, heater_actuator, fan_actuator]
    # Start threads
    for d in devices:
        threading.Thread(target=d.run, daemon=True).start()
    logger.info(f"--- House {HOUSE} Room {ROOM} Simulation Active ---")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down devices...")
        for d in devices:
            d.stop()