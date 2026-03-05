import time
import json
import paho.mqtt.client as mqtt
from catalog_client import CatalogClient

class BaseIoTComponent:
    def __init__(self, house_id, bedroom_id, comp_id, catalog_url, broker_ip, comp_type_code):
        self.house_id = house_id
        self.bedroom_id = bedroom_id
        self.comp_id = comp_id
        self.broker_ip = broker_ip
        
        # Determina la chiave ID corretta in base al tipo per il CatalogClient
        # 0=Service, 1=Sensor, 2=Actuator
        id_key = 'serviceID' if comp_type_code == 0 else 'sensorID' if comp_type_code == 1 else 'ActuatorID'
        
        self.service_info = {
            id_key: comp_id,
            "name": comp_id,
            "host": "localhost",
            "port": 0,
            "type": "BetterSleep_Component"
        }
        
        # Inizializza e avvia la registrazione tramite il CatalogClient 
        self.catalog = CatalogClient(catalog_url, self.service_info, type=comp_type_code)
        self.catalog.register()
        self.catalog.start_background_loop()
        
        self.client = mqtt.Client(comp_id)

    def connect_mqtt(self):
        self.client.connect(self.broker_ip, 1883)
        self.client.loop_start()

class Sensor(BaseIoTComponent):
    def __init__(self, house_id, bedroom_id, sensor_id, subtype, catalog_url, broker_ip):
        super().__init__(house_id, bedroom_id, sensor_id, catalog_url, broker_ip, comp_type_code=1)
        self.subtype = subtype
        self.topic = f"House/{house_id}/Bedroom/{bedroom_id}/sensor/{sensor_id}/data/{subtype}"

    def publish_data(self, value):
        payload = {"timestamp": time.time(), "value": value, "unit": "raw"}
        self.client.publish(self.topic, json.dumps(payload))
        print(f"[PUBLISH] {self.subtype} data sent: {value}")

class Actuator(BaseIoTComponent):
    def __init__(self, house_id, bedroom_id, act_id, catalog_url, broker_ip):
        super().__init__(house_id, bedroom_id, act_id, catalog_url, broker_ip, comp_type_code=2)
        self.topic = f"House/{house_id}/Bedroom/{bedroom_id}/actuator/{act_id}/command"
        self.client.on_message = self.on_message
        
    def start(self):
        self.connect_mqtt()
        self.client.subscribe(self.topic)
        print(f"Actuator {self.comp_id} listening on {self.topic}")

    def on_message(self, client, userdata, msg):
        pass # implemented by subclasses
