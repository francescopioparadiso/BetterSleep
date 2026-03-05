import json
import paho.mqtt.client as mqtt
from catalog_client import CatalogClient

HOUSE_ID, BEDROOM_ID, ACT_ID = "H1", "B1", "LIGHT01"
TOPIC = f"House/{HOUSE_ID}/Bedroom/{BEDROOM_ID}/actuator/{ACT_ID}/command"

def on_message(client, userdata, msg):
    data = json.loads(msg.payload.decode())
    # Outputting value to console as requested
    print(f"[LIGHT STATUS] Brightness set to: {data.get('value')}")

catalog = CatalogClient("http://catalog-service:8080")
catalog.register({"id": ACT_ID, "type": "light"}, is_service=False)

client = mqtt.Client(ACT_ID)
client.on_message = on_message
client.connect("mqtt-broker-ip", 1883)
client.subscribe(TOPIC)
client.loop_forever()
