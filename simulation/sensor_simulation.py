import math
import os
import random
import re
import sys
from datetime import datetime, timedelta

SIMULATION_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SIMULATION_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import requests


from common_simulation import apply_runtime_overrides, build_url, get_user_service_endpoint, load_json_file
from time_series.mongo_db import MongoDB


DAYS = 7
STEP_SECONDS = 60  # un punto ogni minuto
BATCH_SIZE = 5000
BACKFILL_SOURCE = "backfill_week"

SENSOR_KEYS = ("temperature", "heart_rate", "presence", "vibration")

SENSOR_TYPE_CODES = {"ambient_temp": 0, "presence": 2, "heart_rate": 3, "vibration": 4}
SENSOR_UNITS     = {"ambient_temp": "degC", "presence": "", "heart_rate": "bpm", "vibration": "g"}
SENSOR_LABELS    = {"ambient_temp": "Temperature", "presence": "Presence", "heart_rate": "Heart Rate", "vibration": "Vibration"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noise(sensor_id, when, salt, low, high):
    seed = f"{sensor_id}:{int(when.timestamp())}:{salt}"
    return random.Random(seed).uniform(low, high)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _sensor_id(raw, room_id, sensor_type):
    try:
        return int(raw)
    except (TypeError, ValueError):
        pass
    digits = re.findall(r"\d+", str(raw))
    code = SENSOR_TYPE_CODES.get(sensor_type, 99)
    if digits:
        return (int(room_id) * 1000) + (code * 100) + int(digits[-1])
    checksum = sum(ord(c) for c in str(raw)) % 100
    return (int(room_id) * 1000) + (code * 100) + checksum


# ---------------------------------------------------------------------------
# Value generation
# ---------------------------------------------------------------------------

def generate_value(sensor_type, sensor_id, when):
    doy         = when.timetuple().tm_yday
    hour_frac   = when.hour + when.minute / 60.0
    annual_wave = math.sin((2 * math.pi * doy) / 365.25)
    daily_wave  = math.sin((2 * math.pi * hour_frac) / 24.0)
    night       = when.hour >= 22 or when.hour < 7
    occupied    = 1 if _noise(sensor_id, when, "presence", 0.0, 1.0) < (0.92 if night else 0.12) else 0

    if sensor_type == "ambient_temp":
        v = 21.5 + 5.5 * annual_wave + 2.2 * daily_wave + _noise(sensor_id, when, "temp", -0.8, 0.8)
        return round(_clamp(v, 14.0, 30.0), 2)

    if sensor_type == "presence":
        return occupied

    if sensor_type == "heart_rate":
        v = (57.0 if occupied else 71.0) + 2.5 * daily_wave + _noise(sensor_id, when, "heart_rate", -4.0, 4.0)
        return round(_clamp(v, 48.0, 110.0), 2)

    if sensor_type == "vibration":
        v = (0.005 + abs(daily_wave) * 0.01 + _noise(sensor_id, when, "vibration_sleep", 0.0, 0.015)
             if occupied else _noise(sensor_id, when, "vibration_idle", 0.0, 0.003))
        return round(_clamp(v, 0.0, 0.06), 4)

    return 0.0


# ---------------------------------------------------------------------------
# Mongo write
# ---------------------------------------------------------------------------

def backfill_sensor(measurements, sensor, room, start_dt, end_dt):
    sensor_type      = sensor.get("type")
    sensor_type_code = SENSOR_TYPE_CODES.get(sensor_type)
    if sensor_type_code is None:
        print(f"[SKIP] tipo '{sensor_type}' non supportato")
        return 0

    room_id  = int(sensor.get("roomID") or room["id"])
    house_id = int(sensor.get("houseID") or room["house_id"])
    sid      = _sensor_id(sensor.get("sensorID"), room_id, sensor_type)
    name     = SENSOR_LABELS.get(sensor_type, sensor_type)
    unit     = SENSOR_UNITS.get(sensor_type, "")

    # Delete old data for the same period to avoid duplicates
    measurements.delete_many({
        "room_id": room_id, "sensor_id": sid, "sensor_type": sensor_type_code,
        "backfill_source": BACKFILL_SOURCE,
        "e.t": {"$gte": int(start_dt.timestamp()), "$lte": int(end_dt.timestamp())},
    })

    batch, count = [], 0
    ts, step = start_dt, timedelta(seconds=STEP_SECONDS)

    while ts <= end_dt:
        # Keep the integer epoch timestamp for compatibility and add an ISO timestamp string
        batch.append({
            "bn": f"{house_id}:{room_id}:{sid}:{sensor_type_code}",
            "e": [{"n": name, "v": generate_value(sensor_type, sid, ts), "u": unit, "t": int(ts.timestamp()), "ts": ts.isoformat()}],
            "house_id": house_id, "room_id": room_id,
            "sensor_id": sid, "sensor_type": sensor_type_code,
            "backfill_source": BACKFILL_SOURCE,
        })
        if len(batch) >= BATCH_SIZE:
            measurements.insert_many(batch, ordered=False)
            count += len(batch)
            batch = []
        ts += step

    if batch:
        measurements.insert_many(batch, ordered=False)
        count += len(batch)

    print(f"[OK] room={room_id} sensor={sid} ({sensor_type}) → {count} data points")
    return count


# ---------------------------------------------------------------------------
# Main — modifica qui i path se necessario
# ---------------------------------------------------------------------------

def main(
    simulation_conf_path=None,
    time_series_conf_path=None,
):
    if simulation_conf_path is None:
        simulation_conf_path = os.path.join(SIMULATION_DIR, "conf.json")
    if time_series_conf_path is None:
        time_series_conf_path = os.path.join(PROJECT_ROOT, "time_series", "conf.json")
    sim_conf = apply_runtime_overrides(load_json_file(simulation_conf_path))
    ts_conf  = load_json_file(time_series_conf_path)

    end_dt   = datetime.now().replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=DAYS)
    print(f"Backfill last {DAYS} days: {start_dt.isoformat()} → {end_dt.isoformat()}")

    catalog_url      = sim_conf["catalog"]["url"]
    user_service_url = get_user_service_endpoint(catalog_url)

    rooms = requests.get(build_url(user_service_url, "getAllRooms"), timeout=10).json().get("rooms", [])
    if not rooms:
        print("No rooms found.")
        return

    mongo        = MongoDB(ts_conf)
    measurements = mongo.db["measurements"]

    total_points = 0
    for room in rooms:
        if room.get("id") is None:
            continue
        sensors = [
            {**sim_conf["sensors"][key], "roomID": room.get("id"), "houseID": room.get("house_id")}
            for key in SENSOR_KEYS
        ]
        for sensor in sensors:
            total_points += backfill_sensor(measurements, sensor, room, start_dt, end_dt)

    mongo.client_mongo.close()
    print(f"\nCompleted: {total_points} total data points across {len(rooms)} rooms.")


if __name__ == "__main__":
    main()
