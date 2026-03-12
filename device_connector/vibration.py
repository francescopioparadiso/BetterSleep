import time, json
import paho.mqtt.client as mqtt
from catalog_client import CatalogClient

HOUSE_ID, BEDROOM_ID, SENSOR_ID = "H1", "B1", "VIB01"
TOPIC = f"House/{HOUSE_ID}/Bedroom/{BEDROOM_ID}/sensor/{SENSOR_ID}/data/vibration"

catalog = CatalogClient("http://catalog-service:8080")
catalog.register({"id": SENSOR_ID, "house": HOUSE_ID, "room": BEDROOM_ID}, is_service=False)

client = mqtt.Client(SENSOR_ID)
client.connect("mqtt-broker-ip", 1883)

while True:
    val = input(f"Enter Vibration level (e.g. 0-10) for {SENSOR_ID}: ")
    payload = {"timestamp": time.time(), "value": val}
    client.publish(TOPIC, json.dumps(payload))
