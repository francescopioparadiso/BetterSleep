import time
import json
import paho.mqtt.client as mqtt
from catalog_client import CatalogClient

HOUSE_ID = "H1"
BEDROOM_ID = "B1"
SENSOR_ID = "HR01"
# Path: House/+/Bedroom/+/sensor/+/data/subtype
TOPIC = f"House/{HOUSE_ID}/Bedroom/{BEDROOM_ID}/sensor/{SENSOR_ID}/data/heartrate"

catalog = CatalogClient("http://catalog-service:8080")
catalog.register({"id": SENSOR_ID, "house": HOUSE_ID, "room": BEDROOM_ID}, is_service=False)

client = mqtt.Client(SENSOR_ID)
client.connect("mqtt-broker-ip", 1883)

while True:
    # Read from standard input as requested
    val = input(f"Enter current Heart Rate (bpm) for {SENSOR_ID}: ")
    payload = {"timestamp": time.time(), "value": val, "unit": "bpm"}
    client.publish(TOPIC, json.dumps(payload))
