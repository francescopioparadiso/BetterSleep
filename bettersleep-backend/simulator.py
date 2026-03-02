import os
import time
import json
import random
from datetime import datetime, timedelta, time as dt_time
import paho.mqtt.client as mqtt
from supabase import create_client, Client
from dotenv import load_dotenv

class SensorSimulator:
    def __init__(self):
        # Load Configurations
        load_dotenv()
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_KEY")
        self.broker = os.environ.get("MQTT_BROKER")
        self.port = int(os.environ.get("MQTT_PORT"))
        
        # Initialize Clients
        self.supabase: Client = create_client(self.url, self.key)
        self.client = mqtt.Client(client_id="BetterSleep_Simulator")

    def parse_time(self, time_str, default_hour, default_minute):
        if not time_str:
            return dt_time(default_hour, default_minute)
        try:
            parts = time_str.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except:
            return dt_time(default_hour, default_minute)

    def is_bedtime(self, current_time, bed_time, wake_time):
        if bed_time > wake_time: 
            return current_time >= bed_time or current_time < wake_time
        else: 
            return bed_time <= current_time < wake_time

    def get_elapsed_minutes(self, current_dt, bed_time, wake_time):
        bed_datetime = current_dt.replace(hour=bed_time.hour, minute=bed_time.minute, second=0, microsecond=0)
        if bed_time > wake_time and current_dt.time() < wake_time:
            bed_datetime -= timedelta(days=1)
        elif bed_time < wake_time and current_dt.time() < bed_time:
            bed_datetime -= timedelta(days=1)
            
        return max(0, (current_dt - bed_datetime).total_seconds() / 60.0)

    def get_context(self):
        sensors = self.supabase.table("sensors").select("*").execute().data
        rooms = self.supabase.table("rooms").select("id, user_id").execute().data
        prefs = self.supabase.table("global_preferences").select("user_id, bedtime, wake_time").execute().data
        
        user_prefs = {p["user_id"]: p for p in prefs if p.get("user_id")}
        room_users = {r["id"]: r.get("user_id") for r in rooms}
        
        sensors_by_room = {}
        for s in sensors:
            rid = s["room_id"]
            if rid not in sensors_by_room:
                sensors_by_room[rid] = []
            sensors_by_room[rid].append(s)
            
        return sensors_by_room, room_users, user_prefs

    def generate_reading(self, sensor_type, target, is_night, has_presence, is_occupied, elapsed_minutes=0):
        if sensor_type == "presence":
            return 1.0 if is_night else 0.0
            
        elif sensor_type == "hr":
            if not is_night or is_occupied == 0.0:
                return None 
            
            cycle_length = 90
            time_in_cycle = elapsed_minutes % cycle_length
            cycle_number = elapsed_minutes // cycle_length
            
            if 120 <= elapsed_minutes <= 135:
                return round(random.uniform(82, 88), 0) 
            
            if elapsed_minutes < 15:
                return round(random.uniform(60, 68), 0)
                
            if time_in_cycle < 20:
                return round(random.uniform(58, 68), 0)
            elif time_in_cycle < 60:
                if cycle_number < 3:
                    return round(random.uniform(48, 54), 0)
                else:
                    return round(random.uniform(58, 65), 0)
            elif time_in_cycle < 75:
                return round(random.uniform(60, 68), 0)
            else:
                return round(random.uniform(72, 78), 0)
                
        elif sensor_type == "temperature":
            return round(random.uniform(target - 0.5, target + 0.5), 1)
        elif sensor_type == "humidity":
            return round(random.uniform(max(0, target - 2), min(100, target + 2)), 0)
        elif sensor_type == "light":
            return 0.0 if is_night else round(random.uniform(80, 100), 0)
            
        return target

    # ==========================================
    # MODULARIZED FUNCTIONS
    # ==========================================

    def clean(self):
        """Clears old database entries."""
        print("🧹 Clearing old database entries...")
        try:
            self.supabase.table("sensor_data").delete().neq("value", -99999).execute()
            print("✅ Database cleared.")
        except Exception as e:
            print(f"⚠️ Could not clear DB: {e}")

    def backfill(self, days=1095):
        """Generates historical 1-hour interval data for up to 3 years (ending yesterday)."""
        print(f"⏳ Backfilling {days} days of historical data (1-hour intervals)...")
        sensors_by_room, room_users, user_prefs = self.get_context()
        
        now = datetime.now()
        end_dt = now - timedelta(days=1) # Stop exactly 1 day ago
        current_dt = now - timedelta(days=days)
        batch = []
        
        while current_dt < end_dt:
            curr_time = current_dt.time()
            for room_id, room_sensors in sensors_by_room.items():
                user_id = room_users.get(room_id)
                prefs = user_prefs.get(user_id, {}) if user_id else {}
                
                bed_time = self.parse_time(prefs.get("bedtime"), 22, 30)
                wake_time = self.parse_time(prefs.get("wake_time"), 7, 0)
                
                is_night = self.is_bedtime(curr_time, bed_time, wake_time)
                is_occupied = 1.0 if is_night else 0.0
                has_presence = any(s["sensor_type"] == "presence" for s in room_sensors)
                elapsed_minutes = self.get_elapsed_minutes(current_dt, bed_time, wake_time) if is_night else 0
                
                for sensor in room_sensors:
                    target = sensor.get("bedtime_value") if is_night else sensor.get("wakeup_value")
                    if sensor["sensor_type"] == "hr": target = 70.0 
                    
                    val = self.generate_reading(sensor["sensor_type"], target or 0.0, is_night, has_presence, is_occupied, elapsed_minutes)
                    
                    if val is not None:
                        batch.append({"sensor_id": sensor["id"], "value": val, "created_at": current_dt.isoformat()})
                        
            if len(batch) >= 5000:
                self.supabase.table("sensor_data").insert(batch).execute()
                print(f"⬆️ Uploaded batch... (Date: {current_dt.strftime('%Y-%m-%d')})")
                batch = []
            
            current_dt += timedelta(hours=1)
            
        if batch:
            self.supabase.table("sensor_data").insert(batch).execute()
        print("✅ Backfill complete.")

    def generate_optimal_data(self):
        """Generates 5-minute interval optimal sleep data strictly for the last 24 hours."""
        print("⏳ Generating optimal sleep data for yesterday (5-min intervals)...")
        sensors_by_room, room_users, user_prefs = self.get_context()
        
        now = datetime.now()
        current_dt = now - timedelta(days=1)
        batch = []
        
        while current_dt < now:
            curr_time = current_dt.time()
            for room_id, room_sensors in sensors_by_room.items():
                user_id = room_users.get(room_id)
                prefs = user_prefs.get(user_id, {}) if user_id else {}
                
                bed_time = self.parse_time(prefs.get("bedtime"), 22, 30)
                wake_time = self.parse_time(prefs.get("wake_time"), 7, 0)
                
                is_night = self.is_bedtime(curr_time, bed_time, wake_time)
                is_occupied = 1.0 if is_night else 0.0
                has_presence = any(s["sensor_type"] == "presence" for s in room_sensors)
                elapsed_minutes = self.get_elapsed_minutes(current_dt, bed_time, wake_time) if is_night else 0
                
                for sensor in room_sensors:
                    target = sensor.get("bedtime_value") if is_night else sensor.get("wakeup_value")
                    if sensor["sensor_type"] == "hr": target = 70.0 
                    
                    val = self.generate_reading(sensor["sensor_type"], target or 0.0, is_night, has_presence, is_occupied, elapsed_minutes)
                    
                    if val is not None:
                        batch.append({"sensor_id": sensor["id"], "value": val, "created_at": current_dt.isoformat()})
                        
            if len(batch) >= 5000:
                self.supabase.table("sensor_data").insert(batch).execute()
                batch = []
                
            current_dt += timedelta(minutes=5)
            
        if batch:
            self.supabase.table("sensor_data").insert(batch).execute()
        print("✅ Optimal data generated!")

    def generate_live_data(self):
        """Standard live loop running every 10 seconds."""
        sensors_by_room, room_users, user_prefs = self.get_context()
        now = datetime.now()
        curr_time = now.time()
        
        print(f"\n🔍 Live Snapshot | Found {sum(len(s) for s in sensors_by_room.values())} active sensors.")
        
        for room_id, room_sensors in sensors_by_room.items():
            user_id = room_users.get(room_id)
            prefs = user_prefs.get(user_id, {}) if user_id else {}
            
            bed_time = self.parse_time(prefs.get("bedtime"), 22, 30)
            wake_time = self.parse_time(prefs.get("wake_time"), 7, 0)
            
            is_night = self.is_bedtime(curr_time, bed_time, wake_time)
            is_occupied = 1.0 if is_night else 0.0
            has_presence = any(s["sensor_type"] == "presence" for s in room_sensors)
            elapsed_minutes = self.get_elapsed_minutes(now, bed_time, wake_time) if is_night else 0
            
            for sensor in room_sensors:
                sensor_id = sensor["id"]
                sensor_type = sensor["sensor_type"]
                
                target = sensor.get("bedtime_value") if is_night else sensor.get("wakeup_value")
                if sensor_type == "hr": target = 70.0 
                
                live_value = self.generate_reading(sensor_type, target or 0.0, is_night, has_presence, is_occupied, elapsed_minutes)
                
                if live_value is None: continue
                
                topic = f"bettersleep/sensors/{sensor_id}"
                payload = json.dumps({"type": sensor_type, "value": live_value})
                self.client.publish(topic, payload)
                
                if sensor_type == "presence":
                    status = "🛌 Occupied" if live_value == 1.0 else "🚶‍♂️ Out of bed"
                    print(f"📡 Emitted: PRESENCE | Status: {status}")
                elif sensor_type == "hr":
                    print(f"📡 Emitted: HR       | ❤️ Live: {live_value} bpm")
                else:
                    print(f"📡 Emitted: {sensor_type.upper().ljust(8)} | Target: {target or 0.0} -> Live: {live_value}")

    def run(self):
        # 1. Clear DB
        self.clean()
        
        # 2. Generate Optimal Data for Yesterday
        self.generate_optimal_data()
        
        # Note: self.backfill() is intentionally omitted here based on your request, 
        # but you can easily call it if you ever want to re-populate history!
        
        # 3. Connect to Live Broker
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()
        
        # 4. Stream Live Data
        try:
            while True:
                self.generate_live_data()
                time.sleep(10)  
        except KeyboardInterrupt:
            self.stop()
            
    def stop(self):
        print("🛑 Simulator stopped.")
        self.client.loop_stop()
        self.client.disconnect()

# Entry point
if __name__ == "__main__":
    simulator = SensorSimulator()
    simulator.run()