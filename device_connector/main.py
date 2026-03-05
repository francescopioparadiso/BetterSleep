import threading
import time
import json
from models import Sensor, Actuator

# SENSORS 

class PresenceSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            val = input(f"\n[{self.comp_id}] Enter Presence (1=In Bed, 0=Empty): ")
            self.publish_data(val)

class HeartRateSensor(Sensor):
    def __init__(self, delay_minutes, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.presence_topic = f"House/{self.house_id}/Bedroom/{self.bedroom_id}/sensor/+/data/presence"
        self.is_present = False
        self.presence_start_time = None
        
        # Per fare test rapidi, se delay_minutes è molto piccolo (es. 0.1), si sbloccherà in pochi secondi.
        # Usa 20 per il comportamento reale richiesto.
        self.required_delay_seconds = delay_minutes * 60 

    def on_presence_update(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        val = str(data['value'])
        
        if val == "1" and not self.is_present:
            # L'utente è appena entrato nel letto, avvio il timer
            self.is_present = True
            self.presence_start_time = time.time()
            print(f"\n[{self.comp_id}] Presence detected. Starting {self.required_delay_seconds/60} min timer before HR transmission is allowed.")
        elif val == "0":
            # L'utente si è alzato, resetto tutto
            self.is_present = False
            self.presence_start_time = None
            print(f"\n[{self.comp_id}] Bed is empty. HR transmission blocked.")

    def run(self):
        self.connect_mqtt()
        self.client.subscribe(self.presence_topic)
        self.client.on_message = self.on_presence_update
        
        while True:
            val = input(f"\n[{self.comp_id}] Enter Heart Rate: ")
            
            if self.is_present and self.presence_start_time:
                elapsed = time.time() - self.presence_start_time
                if elapsed >= self.required_delay_seconds:
                    self.publish_data(val)
                else:
                    remaining = int(self.required_delay_seconds - elapsed)
                    print(f"[{self.comp_id}] Blocked: Waiting {remaining} more seconds before starting HR transmission.")
            else:
                print(f"[{self.comp_id}] Blocked: User is not in bed.")

class VibrationSensor(Sensor):
    def run(self):
        self.connect_mqtt()
        while True:
            val = input(f"\n[{self.comp_id}] Enter Vibration Level: ")
            self.publish_data(val)

# ACTUATORS 

class SmartLight(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n>> [ACTUATOR - LIGHT] Setting brightness to: {data['value']}\n")

class Fan(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n>> [ACTUATOR - FAN] Status changed to: {data['value']}\n")

class Heater(Actuator):
    def on_message(self, client, userdata, msg):
        data = json.loads(msg.payload.decode())
        print(f"\n>> [ACTUATOR - HEATER] Status changed to: {data['value']}\n")

# MAIN EXECUTION

if __name__ == "__main__":
    CATALOG_URL = "http://127.0.0.1:8080" 
    BROKER_IP = "broker.hivemq.com"     
    H_ID, B_ID = "House01", "Bedroom01"

    # Inizializza Componenti
    presence = PresenceSensor(H_ID, B_ID, "PRES_01", "presence", CATALOG_URL, BROKER_IP)
    
    # IMPORTANTE: Qui passi i minuti di ritardo (es. 20). 
    # Ho messo 0.16 (circa 10 secondi) ma può essere cambiato
    heart_rate = HeartRateSensor(0.16, H_ID, B_ID, "HR_01", "heartrate", CATALOG_URL, BROKER_IP)
    
    body_temp = BodyTemperatureSensor(H_ID, B_ID, "BT_01", "body_temperature", CATALOG_URL, BROKER_IP)
    vibration = VibrationSensor(H_ID, B_ID, "VIB_01", "vibration", CATALOG_URL, BROKER_IP)
    
    light = SmartLight(H_ID, B_ID, "LIGHT_01", CATALOG_URL, BROKER_IP)
    fan = Fan(H_ID, B_ID, "FAN_01", CATALOG_URL, BROKER_IP)
    heater = Heater(H_ID, B_ID, "HEAT_01", CATALOG_URL, BROKER_IP)

    # Avvia Attuatori
    light.start()
    fan.start()
    heater.start()

    # Avvia Sensori (Thread separati per lo standard input)
    threading.Thread(target=presence.run, daemon=True).start()
    threading.Thread(target=heart_rate.run, daemon=True).start()
    threading.Thread(target=body_temp.run, daemon=True).start()
    threading.Thread(target=vibration.run, daemon=True).start()

    print("--- BetterSleep Device Connector Started ---")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
