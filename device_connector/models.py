import logging
import sys
import os
import time
import json
import random

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.common import init_mqtt_helper

logger = logging.getLogger(__name__)



class BaseIoTComponent:
    def __init__(self, config):
        self.config = config
        self.catalog_url = config.get("catalogURL", "http://localhost:8080")
        self.service_info = config.get("serviceInfo", {})
        self.remove_interval = config.get("removeInterval", 30)
        self.MQTT_info = config.get("MQTT", {})
        self.timestamp_provider = time.time

        # 1. Identify Device Type
        if "sensorID" in self.service_info:
            self.id_key = "sensorID"
            self.type_device = 1
            self.category = "sensor"
        elif "ActuatorID" in self.service_info:
            self.id_key = "ActuatorID"
            self.type_device = 2
            self.category = "actuator"
        print(self.service_info)
        self.id=None
        self.comp_id = self.service_info.get(self.id_key)

        # 2. Setup Topics
        self._setup_topics()

        # 3. Catalog and MQTT
        self.catalog = CatalogClient(
            catalog_url=self.catalog_url,
            service_info=self.service_info,
            remove_interval=self.remove_interval,
            type_device=self.type_device
        )

        self.catalog.register()
        self.catalog.start_background_loop()
        self.init_mqtt_client()

    def _setup_topics(self):
        """Resolves placeholders in topics from config or generates defaults."""
        # Mapping for string formatting
        mapping = {
            "houseID": str(self.service_info.get("houseID", "")),
            "roomID": str(self.service_info.get("roomID", "")),
            "sensorID": str(self.service_info.get("sensorID", "")),
            "ActuatorID": str(self.service_info.get("ActuatorID", "")),
            "type": str(self.service_info.get("type", ""))
        }

        # Handle topic_publish
        tp = self.MQTT_info.get("topic_publish")
        if tp:
            self.topic_publish = tp.format(**mapping)
        else:
            # Fallback to your base pattern
            self.topic_publish = f"House/{mapping['houseID']}/Bedroom/{mapping['roomID']}/{self.category}/{self.comp_id}/{mapping['type']}/data"

        # Handle topic_subscribe (from config)
        ts = self.MQTT_info.get("topic_subscribe")
        print("topic_subscribe from config:", ts)
        if ts:
            # Convert single string to list for consistency
            ts_list = ts if isinstance(ts, list) else [ts]
            # Resolve placeholders for every topic in the list
            self.topic_subscribe_list = [t.format(**mapping) for t in ts_list]
        else:
            self.topic_subscribe_list = []

    def init_mqtt_client(self):
        try:
            # Fallback generator for clientID
            def generate_client_id():
                return f"{self.category}_{self.comp_id}_{random.randint(0, 1000)}"

            self.mqtt_client = init_mqtt_helper(self, self.MQTT_info, logger, clientid_fallback=generate_client_id)
            if self.mqtt_client is None:
                sys.exit(1)


        except Exception as e:
            logger.error(f"MQTT init failed: {e}")
            sys.exit(1)

    def stop(self):
        self.catalog.unregister()
        self.mqtt_client.stop()

    def publish(self, message, command_topic=None):
        try:
            self.mqtt_client.myPublish(command_topic, message)
            logger.info(f"Published message to {command_topic}: {message}")
        except Exception as e:
            logger.error(f"Error publishing message: {e}")

    def publish_data(self, value, unit=None, timestamp=None, name=None):
        """Generic method to publish data for both sensors and actuators.

        Args:
            value: The data value to publish
            unit: Unit of measurement (optional)
            timestamp: Timestamp (defaults to current time)
            name: Name of the measurement (optional, defaults to sensor_type_long for sensors)
        """
        house_id = self.service_info.get("houseID")
        room_id = self.service_info.get("roomID")

        if self.category == "sensor":
            comp_id = self.service_info.get("sensorID")
        else:
            comp_id = self.service_info.get("ActuatorID")

        if timestamp is None:
            # ensure integer epoch seconds
            timestamp = int(self.timestamp_provider())
        else:
            # coerce provided timestamp to int (accept float or numeric string)
            try:
                timestamp = int(float(timestamp))
            except Exception:
                # fallback: keep as-is (non-numeric) — downstream code should validate
                pass

        # Use provided name, fallback to sensor_type_long for sensors, or use component type
        measurement_name = name or getattr(self, 'sensor_type_long', self.service_info.get('type', 'Value').title())

        payload = {
            "bn": f"{house_id}:{room_id}:{comp_id}:{self.id}",
            "e": [{
                "n": measurement_name,
                "v": value,
                "u": unit,
                "t": timestamp
            }]
        }

        self.publish(payload, command_topic=self.topic_publish)

class Sensor(BaseIoTComponent):

    def __init__(self, config, sensor_type):
        super().__init__(config)
        self.sensor_type = sensor_type
        # Supports fake/virtual time in simulations; defaults to wall-clock time.
        self.timestamp_provider = time.time
        sensortype = {
            0: "Temperature",
            1: "Humidity",
            2: "Presence",
            3: "Heart Rate",
            4: "Vibration"
        }

        # then in your class
        self.sensor_type_long = sensortype.get(sensor_type, "Unknown")
        self.id = sensor_type
class Actuator(BaseIoTComponent):
    def notify(self, topic, payload):
        try:
            data = json.loads(payload)
            self.on_command(topic, data)
        except json.JSONDecodeError:
            logger.error(f"[{self.comp_id}] Invalid JSON: {payload}")

    def on_command(self, topic, data):
        # To be overridden
        pass