"""
BetterSleep Sensor Simulator
Generates realistic sensor data and publishes it via MQTT in SenML format.
Also backfills historical data directly into MongoDB.

Usage:
    python fakesensor.py                  # backfill 7 days + live streaming
    python fakesensor.py --backfill 30    # backfill 30 days + live streaming
    python fakesensor.py --live-only      # live streaming only (no backfill)
    python fakesensor.py --backfill-only  # backfill only, no live data
"""

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import json
import time
import random
import argparse
import logging
import requests
from datetime import datetime, timedelta
from pymongo import MongoClient
from common.MQTT.MyMQTT import MyMQTT

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Sensor type mapping: name -> (numeric_code, unit, measurement_name)
SENSOR_TYPES = {
    'ambient_temp': (0, '°C', 'temperature'),
    'humidity':     (1, '%',  'humidity'),
    'presence':     (2, '',   'presence'),
    'heart_rate':   (3, 'bpm','heart_rate'),
    'vibration':    (4, '',   'vibration'),
    'light':        (5, '%',  'light'),
}

# Load config from conf.json (same directory)
with open(os.path.join(os.path.dirname(__file__), 'conf.json'), 'r') as f:
    CONF = json.load(f)

MQTT_BROKER = CONF['MQTT']['broker']
MQTT_PORT = CONF['MQTT']['port']
MONGO_HOST = CONF['timeSeriesDB']['host']
MONGO_PORT = CONF['timeSeriesDB']['port']
MONGO_USER = CONF['timeSeriesDB']['username']
MONGO_PASS = CONF['timeSeriesDB']['password']
MONGO_DB   = CONF['timeSeriesDB']['database']
USER_SERVICE_URL = "http://127.0.0.1:9095"


class SensorSimulator:
    def __init__(self):
        self.mqtt = MyMQTT("BetterSleep_FakeSensor", MQTT_BROKER, MQTT_PORT, None)
        self.mongo = MongoClient(
            host=MONGO_HOST, port=MONGO_PORT,
            username=MONGO_USER, password=MONGO_PASS,
            serverSelectionTimeoutMS=5000
        )
        self.db = self.mongo[MONGO_DB]
        self.rooms = []

    def start(self):
        self.mqtt.start()
        time.sleep(1)
        self._fetch_rooms()

    def stop(self):
        self.mqtt.stop()
        self.mongo.close()

    def _fetch_rooms(self, backfill_new=False, backfill_days=365):
        """Fetch all rooms from the user service. If backfill_new=True, backfill any newly discovered rooms."""
        try:
            resp = requests.get(f"{USER_SERVICE_URL}/getAllRooms", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            new_rooms = data.get('rooms', [])

            if backfill_new:
                existing_ids = {r['id'] for r in self.rooms}
                added_rooms = [r for r in new_rooms if r['id'] not in existing_ids]
            else:
                added_rooms = []

            self.rooms = new_rooms
            logger.info(f"Found {len(self.rooms)} rooms")
            for r in self.rooms:
                logger.info(f"  Room {r['id']}: '{r['name']}' (house {r['house_id']})")

            if added_rooms:
                logger.info(f"Detected {len(added_rooms)} new room(s), backfilling {backfill_days} days...")
                self._backfill_rooms(added_rooms, days=backfill_days)

        except Exception as e:
            logger.error(f"Failed to fetch rooms: {e}")
            logger.info("Using default room config: house_id=1, room_id=1")
            self.rooms = [{'id': 1, 'house_id': 1, 'name': 'Default Bedroom'}]

    # ---------------------------------------------------------------
    # Data Generation
    # ---------------------------------------------------------------

    def _is_night(self, dt_obj):
        """Check if it's nighttime (22:00 - 07:00)."""
        h = dt_obj.hour
        return h >= 22 or h < 7

    def _get_sleep_elapsed_minutes(self, dt_obj):
        """Minutes elapsed since bedtime (22:00)."""
        if dt_obj.hour >= 22:
            return (dt_obj.hour - 22) * 60 + dt_obj.minute
        elif dt_obj.hour < 7:
            return (dt_obj.hour + 2) * 60 + dt_obj.minute
        return 0

    def generate_value(self, sensor_type, dt_obj, room):
        """Generate a realistic sensor value based on type and time of day."""
        night = self._is_night(dt_obj)
        elapsed = self._get_sleep_elapsed_minutes(dt_obj) if night else 0

        temp_night = room.get('temperature_night', 18)
        temp_morning = room.get('temperature_morning', 22)

        if sensor_type == 'ambient_temp':
            target = temp_night if night else temp_morning
            return round(random.uniform(target - 0.5, target + 0.5), 1)

        elif sensor_type == 'humidity':
            base = 55 if night else 45
            return round(random.uniform(base - 3, base + 3), 0)

        elif sensor_type == 'light':
            if night:
                return 0.0
            h = dt_obj.hour
            if 7 <= h <= 9:
                return round(random.uniform(30, 60), 0)
            elif 10 <= h <= 16:
                return round(random.uniform(70, 100), 0)
            return round(random.uniform(20, 50), 0)

        elif sensor_type == 'presence':
            return 1.0 if night else 0.0

        elif sensor_type == 'heart_rate':
            if not night:
                return None  # No HR when not in bed
            cycle_pos = elapsed % 90
            if elapsed < 15:
                return round(random.uniform(60, 68), 0)
            elif cycle_pos < 20:
                return round(random.uniform(58, 65), 0)
            elif cycle_pos < 60:
                return round(random.uniform(48, 54), 0)
            elif cycle_pos < 75:
                return round(random.uniform(60, 68), 0)
            return round(random.uniform(72, 78), 0)

        elif sensor_type == 'vibration':
            if not night:
                return 0.0
            if random.random() < 0.15:
                return round(random.uniform(0.3, 0.8), 2)
            return round(random.uniform(0.0, 0.1), 2)

        return 0.0

    # ---------------------------------------------------------------
    # SenML message creation
    # ---------------------------------------------------------------

    def _make_senml(self, house_id, room_id, sensor_type, value, timestamp):
        """Create a SenML message."""
        type_code, unit, name = SENSOR_TYPES[sensor_type]
        sensor_id = room_id * 10 + type_code
        return {
            "bn": f"{house_id}:{room_id}:{sensor_id}:{type_code}",
            "e": [{
                "n": name,
                "u": unit,
                "t": timestamp,
                "v": value
            }]
        }

    def _mqtt_topic(self, house_id, room_id, sensor_type):
        """Build MQTT topic matching the TimeSeries subscriber pattern."""
        type_code = SENSOR_TYPES[sensor_type][0]
        sensor_id = room_id * 10 + type_code
        return f"House/{house_id}/Bedroom/{room_id}/sensor/{sensor_type}/{sensor_id}/data"

    # ---------------------------------------------------------------
    # Backfill (direct MongoDB insert)
    # ---------------------------------------------------------------

    def _backfill_rooms(self, rooms, days=365):
        """Insert historical data directly into MongoDB for the given list of rooms."""
        logger.info(f"Backfilling {days} days of historical data for {len(rooms)} room(s)...")
        collection = self.db["measurements"]
        now = datetime.now()
        current = now - timedelta(days=days)
        batch = []
        total = 0

        # Use hourly intervals for data older than 7 days, 15-min for recent data
        recent_cutoff = now - timedelta(days=7)

        while current < now:
            for room in rooms:
                rid, hid = room['id'], room['house_id']
                for stype in SENSOR_TYPES:
                    val = self.generate_value(stype, current, room)
                    if val is None:
                        continue
                    msg = self._make_senml(hid, rid, stype, val, current.timestamp())
                    parts = msg["bn"].split(":")
                    doc = dict(msg)
                    doc["house_id"] = int(parts[0])
                    doc["room_id"] = int(parts[1])
                    doc["sensor_id"] = int(parts[2])
                    doc["sensor_type"] = int(parts[3])
                    batch.append(doc)

            if len(batch) >= 5000:
                collection.insert_many(batch)
                total += len(batch)
                logger.info(f"  Inserted {total} records... (at {current.strftime('%Y-%m-%d %H:%M')})")
                batch = []

            # Hourly for older data, 15-min for recent week
            if current < recent_cutoff:
                current += timedelta(hours=1)
            else:
                current += timedelta(minutes=15)

        if batch:
            collection.insert_many(batch)
            total += len(batch)

        logger.info(f"Backfill complete: {total} records inserted")

    def backfill(self, days=365):
        """Refresh room list and backfill historical data for all rooms."""
        self._fetch_rooms()
        self._backfill_rooms(self.rooms, days=days)

    # ---------------------------------------------------------------
    # Live streaming (MQTT publish)
    # ---------------------------------------------------------------

    def stream_live(self, interval=10):
        """Continuously publish live sensor data via MQTT."""
        logger.info(f"Starting live data stream (every {interval}s)...")
        logger.info("Press Ctrl+C to stop")
        iteration = 0
        try:
            while True:
                # Refresh rooms every 60 seconds; backfill any newly created rooms
                iteration += 1
                if iteration % 6 == 0:
                    self._fetch_rooms(backfill_new=True)
                
                now = datetime.now()
                for room in self.rooms:
                    rid, hid = room['id'], room['house_id']
                    for stype in SENSOR_TYPES:
                        val = self.generate_value(stype, now, room)
                        if val is None:
                            continue
                        msg = self._make_senml(hid, rid, stype, val, now.timestamp())
                        topic = self._mqtt_topic(hid, rid, stype)
                        self.mqtt.myPublish(topic, msg)

                logger.info(f"Published readings for {len(self.rooms)} room(s) at {now.strftime('%H:%M:%S')}")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Stopping live stream...")


def main():
    parser = argparse.ArgumentParser(description="BetterSleep Sensor Simulator")
    parser.add_argument('--backfill', type=int, default=365, help='Days of historical data (default: 365)')
    parser.add_argument('--live-only', action='store_true', help='Skip backfill, only stream live')
    parser.add_argument('--backfill-only', action='store_true', help='Only backfill, no live streaming')
    parser.add_argument('--interval', type=int, default=10, help='Live interval in seconds (default: 10)')
    args = parser.parse_args()

    sim = SensorSimulator()
    try:
        sim.start()
        if not args.live_only:
            sim.backfill(days=args.backfill)
        if not args.backfill_only:
            sim.stream_live(interval=args.interval)
    except Exception as e:
        logger.error(f"Simulator error: {e}")
    finally:
        sim.stop()


if __name__ == "__main__":
    main()