import logging
import sys
import os
import time
import json

# Add parent directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.MQTT.MyMQTT import MyMQTT
from common.catalog_client import CatalogClient

logger = logging.getLogger(__name__)


class BaseIoTComponent:
    def __init__(self, config):
        self.config = config

        # Catalog configuration
        self.catalog_url = config.get("catalogURL", "http://localhost:8080")
        self.service_info = config.get("serviceInfo", {})
        self.remove_interval = config.get("removeInterval", 30)

        # Determine device type
        if "sensorID" in self.service_info:
            self.id_key = "sensorID"
        elif "actuatorID" in self.service_info:
            self.id_key = "actuatorID"
        else:
            raise ValueError("serviceInfo must contain 'sensorID' or 'actuatorID'")

        self.comp_id = self.service_info.get(self.id_key)

        # MQTT configuration
        self.MQTT_info = config["MQTT"]

        # Topics
        self.topic_publish = self.service_info.get("mqtt_topic")
        self.topic_subscribe_raw = self.service_info.get("mqtt_subscribe", [])

        # Catalog client
        self.catalog = CatalogClient(
            catalog_url=self.catalog_url,
            service_info=self.service_info,
            remove_interval=self.remove_interval,
            type_device=self.id_key
        )

        self.catalog.register()
        self.catalog.start_background_loop()

        # MQTT
        self.init_mqtt_client()

    def init_mqtt_client(self):
        try:
            client_id = self.MQTT_info["clientID"]
            broker = self.MQTT_info["broker"]
            port = self.MQTT_info["port"]

            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.mqtt_client.start()

            for topic in self.topic_subscribe_raw:
                self.mqtt_client.mySubscribe(topic)

            logger.info(f"{self.comp_id} connected to MQTT and subscribed to {self.topic_subscribe_raw}")

        except Exception as e:
            logger.error(f"MQTT initialization error: {e}")
            self.catalog.unregister()
            sys.exit(1)

    def publish(self, topic, payload):
        self.mqtt_client.myPublish(topic, json.dumps(payload))

    def stop(self):
        try:
            self.catalog.unregister()
            self.mqtt_client.stop()
        except Exception as e:
            logger.error(f"Error stopping component: {e}")


class Sensor(BaseIoTComponent):

    def __init__(self, config):
        super().__init__(config)
        self.subtype = self.service_info.get("type", "generic")

    def publish_data(self, value, unit="raw"):
        payload = {
            "timestamp": time.time(),
            "value": value,
            "unit": unit #!TODO this need to be SenML compliant
        }

        self.publish(self.topic_publish, payload)

        logger.info(
            f"[SENSOR {self.comp_id}] Published {value} {unit} -> {self.topic_publish}"
        )


class Actuator(BaseIoTComponent):

    def __init__(self, config):
        super().__init__(config)

    def notify(self, topic, payload):
        """
        Called by MyMQTT when a message is received
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Invalid JSON received")
            return

        self.on_command(topic, data)

    def on_command(self, topic, data):
        """
        Override this in subclasses
        """
        logger.info(f"[ACTUATOR {self.comp_id}] Received command: {data}")