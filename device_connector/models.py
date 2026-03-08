import sys
import os

# Add parent directory to path so we can import from common/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time
import json
import paho.mqtt.client as mqtt
from common.catalog_client import CatalogClient

class BaseIoTComponent:
    def __init__(self, config, comp_type_code, broker_ip="broker.hivemq.com"):
        self.config = config
        self.catalog_url = config.get("catalogURL", "http://localhost:8080")
        self.service_info = config.get("serviceInfo", {})
        self.broker_ip = broker_ip
        
        # Determina la chiave ID corretta (0=Service, 1=Sensor, 2=Actuator)
        self.id_key = 'serviceID' if comp_type_code == 0 else 'sensorID' if comp_type_code == 1 else 'ActuatorID'
        self.comp_id = self.service_info.get(self.id_key, "Unknown_ID")
        
        # Inizializza e avvia la registrazione tramite il CatalogClient fornito
        self.catalog = CatalogClient(
            catalog_url=self.catalog_url, 
            service_info=self.service_info, 
            remove_interval=config.get("removeInterval", 30),
            type=comp_type_code
        )
        self.catalog.register()
        self.catalog.start_background_loop()
        
        self.client = mqtt.Client(self.comp_id)

    def connect_mqtt(self):
        self.client.connect(self.broker_ip, 1883)
        self.client.loop_start()

class Sensor(BaseIoTComponent):
    def __init__(self, config, broker_ip="broker.hivemq.com"):
        super().__init__(config, comp_type_code=1, broker_ip=broker_ip)
        # Prende il topic MQTT direttamente dal file di configurazione
        self.topic = self.service_info.get("mqtt_topic")
        self.subtype = self.service_info.get("type")

    def publish_data(self, value):
        payload = {"timestamp": time.time(), "value": value, "unit": "raw"}
        self.client.publish(self.topic, json.dumps(payload))
        print(f"[PUBLISH {self.comp_id}] Inviato {value} su topic: {self.topic}")

class Actuator(BaseIoTComponent):
    def __init__(self, config, broker_ip="broker.hivemq.com"):
        super().__init__(config, comp_type_code=2, broker_ip=broker_ip)
        # Prende il topic MQTT direttamente dal file di configurazione
        self.topic = self.service_info.get("mqtt_topic")
        self.client.on_message = self.on_message
        
    def start(self):
        self.connect_mqtt()
        self.client.subscribe(self.topic)
        print(f"[SUBSCRIBE] Actuator {self.comp_id} in ascolto su {self.topic}")

    def on_message(self, client, userdata, msg):
        pass # Verrà implementato nelle sottoclassi
