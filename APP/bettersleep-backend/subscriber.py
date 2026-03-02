import os
import json
import paho.mqtt.client as mqtt
from supabase import create_client, Client
from dotenv import load_dotenv

class SensorSubscriber:
    def __init__(self):
        # Load Configurations
        load_dotenv()
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_KEY")
        self.broker = os.environ.get("MQTT_BROKER")
        self.port = int(os.environ.get("MQTT_PORT"))

        # Initialize Supabase Client
        self.supabase: Client = create_client(self.url, self.key)
        
        # Initialize MQTT Client & attach callbacks
        self.client = mqtt.Client(client_id="BetterSleep_Ingester")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def on_connect(self, client, userdata, flags, rc):
        print("✅ Connected to MQTT Broker!")
        # Subscribe to ALL sensors using the # wildcard
        self.client.subscribe("bettersleep/sensors/#")
        print("🎧 Listening for sensor data...")

    def on_message(self, client, userdata, msg):
        try:
            # Decode the JSON message
            payload = json.loads(msg.payload.decode())
            
            # Extract the sensor UUID from the end of the topic (bettersleep/sensors/<UUID>)
            sensor_id = msg.topic.split("/")[-1]
            live_value = payload.get("value")
            
            # Save straight to Supabase Timeseries table!
            self.supabase.table("sensor_data").insert({
                "sensor_id": sensor_id,
                "value": live_value
            }).execute()
            
            print(f"💾 Saved to DB | Sensor: {sensor_id[:8]}... | Value: {live_value}")
            
        except Exception as e:
            print(f"❌ Error processing message: {e}")

    def run(self):
        """Connects to the broker and runs the listening loop forever."""
        self.client.connect(self.broker, self.port, 60)
        
        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        """Safely shuts down the ingester."""
        print("🛑 Ingester stopped.")
        self.client.disconnect()

# Entry point
if __name__ == "__main__":
    subscriber = SensorSubscriber()
    subscriber.run()