import logging
import sys
import os
import time
import json
import random

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.MQTT.MyMQTT import MyMQTT
from common.catalog_client import CatalogClient

logger = logging.getLogger(__name__)


class BaseIoTComponent:
    def __init__(self, config):
        self.config = config
        self.catalog_url = config.get("catalogURL", "http://localhost:8080")
        self.service_info = config.get("serviceInfo", {})
        self.remove_interval = config.get("removeInterval", 30)
        self.MQTT_info = config.get("MQTT", {})

        # 1. Identify Device Type
        if "sensorID" in self.service_info:
            self.id_key = "sensorID"
            self.type_device = 1
            self.category = "sensor"
        elif "ActuatorID" in self.service_info:
            self.id_key = "ActuatorID"
            self.type_device = 2
            self.category = "actuator"

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
        if ts:
            # Convert single string to list for consistency
            ts_list = ts if isinstance(ts, list) else [ts]
            # Resolve placeholders for every topic in the list
            self.topic_subscribe_list = [t.format(**mapping) for t in ts_list]
        else:
            self.topic_subscribe_list = []

    def init_mqtt_client(self):
        try:
            # Ensure clientID exists
            client_id = self.MQTT_info.get("clientID") or f"{self.category}_{self.comp_id}_{random.randint(0, 1000)}"
            broker = self.MQTT_info["broker"]
            port = self.MQTT_info["port"]

            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.mqtt_client.start()

            # Subscribe to all resolved topics
            for topic in self.topic_subscribe_list:
                self.mqtt_client.mySubscribe(topic)
                logger.info(f"[{self.comp_id}] Subscribed to: {topic}")

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

class Sensor(BaseIoTComponent):

    def __init__(self, config, sensor_type):
        super().__init__(config)
        self.sensor_type = sensor_type
        sensortype = {
            0: "Temperature",
            1: "Humidity",
            2: "Presence",
            3: "Heart Rate",
            4: "Vibration"
        }

        # then in your class
        self.sensor_type_long = sensortype.get(sensor_type, "Unknown")

    def publish_data(self, value, unit=None):
        house_id = self.service_info.get("houseID")
        room_id = self.service_info.get("roomID")
        sensor_id = self.service_info.get("sensorID")

        payload = {
            "bn": f"{house_id}:{room_id}:{sensor_id}:{self.sensor_type}",
            "e": [{
                "n" : self.sensor_type_long,
                "v": value,
                "u": unit,
                "t": time.time()
            }]
        }

        self.publish(payload, command_topic=self.topic_publish)
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