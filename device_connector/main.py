import threading
import time
import json
import random
from datetime import datetime
from models import Sensor, Actuator

# --- FUNZIONE HELPER PER CREARE LA CONFIGURAZIONE ---
def create_config(catalog_url, comp_id, name, comp_type, house_id, room_id,broker,port,topic_subscribe=None, topic_publish=None, is_sensor=True, clintId=None):
    id_key = "sensorID" if is_sensor else "ActuatorID"

    return {
        "catalogURL": catalog_url,
        "removeInterval": 30,
        "serviceInfo": {
            id_key: comp_id,
            "name": name,
            "type": comp_type,
            "houseID": house_id,
            "roomID": room_id,
        },
        "MQTT": {
            "broker": broker,
            "port": port,
            "topic_subscribe": topic_subscribe if not is_sensor else None, # Solo gli attuatori si iscrivono a un topic
            "topic_publish": topic_publish if is_sensor else None, # Solo i sensori pubblicano su un topic
            "clientID": clintId
        }

    }

# --- SENSORS ---

class PresenceSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            # Genera randomicamente 0 o 1
            val = random.choice([0, 1])
            self.publish_data(val)
            time.sleep(15) # Pubblica ogni 15 secondi

class HeartRateSensor(Sensor):
    def __init__(self, config, broker_ip="broker.hivemq.com"):
        super().__init__(config, broker_ip)
        self.is_sleeping = False
        
        # Topic speciale per ricevere il comando START_SLEEPING
        house = self.service_info.get("houseID")
        room = self.service_info.get("roomID")
        self.trigger_topic = f"House/{house}/Bedroom/{room}/heart_rate"

    def on_trigger_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            if data.get("action") == "START_SLEEPING":
                self.is_sleeping = True
                print(f"\n[HEART RATE TRIGGER] Ricevuto START_SLEEPING! Inizio a inviare dati...\n")
            elif data.get("action") == "STOP_SLEEPING":
                self.is_sleeping = False
                print(f"\n[HEART RATE TRIGGER] Ricevuto STOP_SLEEPING! Mi fermo.\n")
        except json.JSONDecodeError:
            pass

    def run(self):
        self.connect_mqtt()
        # Si iscrive al topic per ascoltare il comando dal Sleep Cycle Manager
        self.client.subscribe(self.trigger_topic)
        self.client.on_message = self.on_trigger_message
        
        print(f"[{self.comp_id}] In attesa del trigger '{self.trigger_topic}' per iniziare...")
        
        while True:
            if self.is_sleeping:
                # Genera un battito cardiaco realistico per quando si dorme
                val = random.randint(55, 75)
                self.publish_data(val)
            time.sleep(5) # Controlla e pubblica ogni 5 secondi

class BodyTemperatureSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            # Genera temperatura tra 36.0 e 37.5 con un decimale
            val = round(random.uniform(36.0, 37.5), 1)
            self.publish_data(val)
            time.sleep(20)

class VibrationSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            val = random.randint(0, 10) # Scala di vibrazione 0-10
            self.publish_data(val)
            time.sleep(10)

# ACTUATORS 
class Fan(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n>> [VENTOLA ATTUATA] Stato modificato a: {data.get('value')} <<\n")

class SmartLight(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n>> [LUCE ATTUATA] Luminosità impostata a: {data.get('value')} <<\n")


# MAIN EXECUTION

if __name__ == "__main__":
    CATALOG_URL = "http://127.0.0.1:8080"
    BROKER_IP = "broker.hivemq.com"
    HOUSE = "1"
    ROOM = "1"

    # 1. Creiamo le configurazioni usando la funzione helper
    conf_pres = create_config(2, CATALOG_URL, "presence_1", "Presence Sensor", "presence", HOUSE, ROOM, BROKER_IP, 1883, topic_publish=f"House/{HOUSE}/Bedroom/{ROOM}/presence")
    conf_hr = create_config(3, CATALOG_URL, "heart_rate_1", "Heart Rate Sensor", "heart_rate", HOUSE, ROOM, BROKER_IP, 1883, topic_publish=f"House/{HOUSE}/Bedroom/{ROOM}/heart_rate")
    conf_temp = create_config(4, CATALOG_URL, "temp_1", "Body Temperature Sensor", "body_temperature", HOUSE, ROOM, BROKER_IP, 1883, topic_publish=f"House/{HOUSE}/Bedroom/{ROOM}/body_temperature")
    conf_vib = create_config(5, CATALOG_URL, "vibration_1", "Vibration Sensor", "vibration", HOUSE, ROOM, BROKER_IP, 1883, topic_publish=f"House/{HOUSE}/Bedroom/{ROOM}/vibration")
    
    # 2. Inizializziamo i componenti passandogli le configurazioni
    presence = PresenceSensor(conf_pres, BROKER_IP)
    heart_rate = HeartRateSensor(conf_hr, BROKER_IP)
    body_temp = BodyTemperatureSensor(conf_temp, BROKER_IP)
    vibration = VibrationSensor(conf_vib, BROKER_IP)
    
    # fan

    # 4. Avvia Sensori in background
    threading.Thread(target=presence.run, daemon=True).start()
    threading.Thread(target=heart_rate.run, daemon=True).start()
    threading.Thread(target=body_temp.run, daemon=True).start()
    threading.Thread(target=vibration.run, daemon=True).start()

    print("--- Sensori e Attuatori in esecuzione automatica ---")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Spegnimento in corso...")
