import time, json
import paho.mqtt.client as mqtt
from catalog_client import CatalogClient

HOUSE_ID, BEDROOM_ID, SENSOR_ID = "H1", "B1", "MAT01"
TOPIC = f"House/{HOUSE_ID}/Bedroom/{BEDROOM_ID}/sensor/{SENSOR_ID}/data/presence"

catalog = CatalogClient("http://catalog-service:8080")
catalog.register({"id": SENSOR_ID, "house": HOUSE_ID, "room": BEDROOM_ID}, is_service=False)

client = mqtt.Client(SENSOR_ID)
client.connect("mqtt-broker-ip", 1883)

while True:
    val = input(f"Enter Presence Status (1 for in-bed, 0 for out) for {SENSOR_ID}: ")
    payload = {"timestamp": time.time(), "value": int(val)}
    client.publish(TOPIC, json.dumps(payload))
