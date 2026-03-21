import argparse
import math
import os
import random
import re
import sys
from datetime import datetime, timedelta

import requests

from common_simulation import build_url, get_user_service_endpoint, load_json_file


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from time_series.mongo_db import MongoDB


BACKFILL_SOURCE = "sensor_simulation"
BATCH_SIZE = 5000
SIMULATION_SENSOR_KEYS = ("temperature", "heart_rate", "presence", "vibration")
DEFAULT_SIMULATED_SENSORS = (
    ("temperature", {"sensorID": "1", "name": "Temperature", "type": "ambient_temp"}),
    ("heart_rate", {"sensorID": "2", "name": "HeartRate", "type": "heart_rate"}),
    ("presence", {"sensorID": "3", "name": "Presence", "type": "presence"}),
    ("vibration", {"sensorID": "4", "name": "Vibration", "type": "vibration"}),
)
SENSOR_TYPE_CODES = {
    "ambient_temp": 0,
    "humidity": 1,
    "presence": 2,
    "heart_rate": 3,
    "vibration": 4,
    "light": 5,
}
SENSOR_UNITS = {
    "ambient_temp": "degC",
    "humidity": "%",
    "presence": "",
    "heart_rate": "bpm",
    "vibration": "g",
    "light": "%",
}
SENSOR_LABELS = {
    "ambient_temp": "Temperature",
    "humidity": "Humidity",
    "presence": "Presence",
    "heart_rate": "Heart Rate",
    "vibration": "Vibration",
    "light": "Light",
}


def normalize_sensor_id(raw_sensor_id, room_id, sensor_type):
    if raw_sensor_id is None:
        raise ValueError("Missing sensorID")

    try:
        return int(raw_sensor_id)
    except (TypeError, ValueError):
        pass

    digits = re.findall(r"\d+", str(raw_sensor_id))
    if digits:
        # Keep a stable numeric key while preserving room scoping and type separation.
        last_digits = int(digits[-1])
        type_code = SENSOR_TYPE_CODES.get(sensor_type, 99)
        return (int(room_id) * 1000) + (type_code * 100) + last_digits

    type_code = SENSOR_TYPE_CODES.get(sensor_type, 99)
    checksum = sum(ord(char) for char in str(raw_sensor_id)) % 100
    return (int(room_id) * 1000) + (type_code * 100) + checksum


def deterministic_noise(sensor_id, when, salt, low, high):
    seed = f"{sensor_id}:{int(when.timestamp())}:{salt}"
    return random.Random(seed).uniform(low, high)


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def build_simulated_room_sensors(room, simulation_conf):
    room_id = room.get("id") or room.get("roomID")
    house_id = room.get("house_id") or room.get("houseID")
    sensors_conf = simulation_conf.get("sensors", {})
    simulated_sensors = []

    # Always synthesize the four bedroom sensors used by the live simulation.
    # This keeps backfill independent from catalog registration state.
    for key, default_sensor_conf in DEFAULT_SIMULATED_SENSORS:
        sensor_conf = sensors_conf.get(key, default_sensor_conf)
        simulated_sensor = {
            "sensorID": sensor_conf.get("sensorID", default_sensor_conf["sensorID"]),
            "name": sensor_conf.get("name", default_sensor_conf["name"]),
            "type": sensor_conf.get("type", default_sensor_conf["type"]),
            "roomID": room_id,
            "houseID": house_id,
        }
        if "topic_publish" in sensor_conf:
            simulated_sensor["topic_publish"] = sensor_conf["topic_publish"]
        if "topic_subscribe" in sensor_conf:
            simulated_sensor["topic_subscribe"] = sensor_conf["topic_subscribe"]
        simulated_sensors.append(simulated_sensor)

    return simulated_sensors


def generate_value(sensor_type, sensor_id, when):
    day_of_year = when.timetuple().tm_yday
    hour_fraction = when.hour + (when.minute / 60.0)
    annual_wave = math.sin((2 * math.pi * day_of_year) / 365.25)
    daily_wave = math.sin((2 * math.pi * hour_fraction) / 24.0)
    occupancy_probability = 0.92 if when.hour >= 22 or when.hour < 7 else 0.12
    occupied = 1 if deterministic_noise(sensor_id, when, "presence", 0.0, 1.0) < occupancy_probability else 0

    if sensor_type == "ambient_temp":
        value = 21.5 + (5.5 * annual_wave) + (2.2 * daily_wave)
        value += deterministic_noise(sensor_id, when, "temp", -0.8, 0.8)
        return round(clamp(value, 14.0, 30.0), 2)

    if sensor_type == "humidity":
        value = 48.0 - (9.0 * daily_wave) + (6.0 * annual_wave)
        value += deterministic_noise(sensor_id, when, "humidity", -3.0, 3.0)
        return round(clamp(value, 25.0, 85.0), 2)

    if sensor_type == "presence":
        return occupied

    if sensor_type == "heart_rate":
        baseline = 57.0 if occupied else 71.0
        baseline += 2.5 * daily_wave
        baseline += deterministic_noise(sensor_id, when, "heart_rate", -4.0, 4.0)
        return round(clamp(baseline, 48.0, 110.0), 2)

    if sensor_type == "vibration":
        if occupied:
            value = 0.005 + abs(daily_wave) * 0.01
            value += deterministic_noise(sensor_id, when, "vibration_sleep", 0.0, 0.015)
        else:
            value = deterministic_noise(sensor_id, when, "vibration_idle", 0.0, 0.003)
        return round(clamp(value, 0.0, 0.06), 4)

    if sensor_type == "light":
        value = 18.0 if when.hour >= 22 or when.hour < 7 else 72.0 + (18.0 * max(daily_wave, 0.0))
        value += deterministic_noise(sensor_id, when, "light", -5.0, 5.0)
        return round(clamp(value, 0.0, 100.0), 2)

    value = 50.0 + deterministic_noise(sensor_id, when, "generic", -10.0, 10.0)
    return round(value, 2)


def fetch_all_rooms(user_service_url):
    response = requests.get(build_url(user_service_url, "getAllRooms"), timeout=10)
    response.raise_for_status()
    return response.json().get("rooms", [])


def create_time_series_db(time_series_conf):
    return MongoDB(time_series_conf)


def iter_measurement_docs(sensor, room, start_dt, end_dt, step_seconds):
    sensor_type = sensor.get("type")
    sensor_type_code = SENSOR_TYPE_CODES.get(sensor_type)
    if sensor_type_code is None:
        raise ValueError(f"Unsupported sensor type '{sensor_type}' for sensor {sensor.get('sensorID')}")

    room_id = int(sensor.get("roomID") or room["id"])
    house_id = int(sensor.get("houseID") or room["house_id"])
    sensor_id = normalize_sensor_id(sensor.get("sensorID"), room_id, sensor_type)
    measurement_name = sensor.get("name") or SENSOR_LABELS.get(sensor_type, sensor_type.replace("_", " ").title())
    unit = SENSOR_UNITS.get(sensor_type, "")
    timestamp = start_dt
    step = timedelta(seconds=step_seconds)

    while timestamp <= end_dt:
        value = generate_value(sensor_type, sensor_id, timestamp)
        unix_timestamp = int(timestamp.timestamp())
        yield {
            "bn": f"{house_id}:{room_id}:{sensor_id}:{sensor_type_code}",
            "e": [{
                "n": measurement_name,
                "v": value,
                "u": unit,
                "t": unix_timestamp,
            }],
            "house_id": house_id,
            "room_id": room_id,
            "sensor_id": sensor_id,
            "sensor_type": sensor_type_code,
            "backfill_source": BACKFILL_SOURCE,
        }
        timestamp += step

def count_measurements(start_dt, end_dt, step_seconds):
    return int(((end_dt - start_dt).total_seconds()) // step_seconds) + 1


def backfill_sensor_history(measurements, sensor, room, start_dt, end_dt, step_seconds):
    room_id = int(sensor.get("roomID") or room["id"])
    sensor_type = sensor.get("type")
    sensor_type_code = SENSOR_TYPE_CODES.get(sensor_type)
    sensor_id = normalize_sensor_id(sensor.get("sensorID"), room_id, sensor_type)
    if sensor_type_code is None:
        print(f"[SKIP] Room {room_id} sensor {sensor_id}: unsupported type '{sensor_type}'")
        return 0

    measurements.delete_many({
        "room_id": room_id,
        "sensor_id": sensor_id,
        "sensor_type": sensor_type_code,
        "backfill_source": BACKFILL_SOURCE,
        "e.t": {
            "$gte": int(start_dt.timestamp()),
            "$lte": int(end_dt.timestamp()),
        },
    })

    inserted_count = 0
    batch = []
    for document in iter_measurement_docs(sensor, room, start_dt, end_dt, step_seconds):
        batch.append(document)
        if len(batch) >= BATCH_SIZE:
            measurements.insert_many(batch, ordered=False)
            inserted_count += len(batch)
            batch = []

    if batch:
        measurements.insert_many(batch, ordered=False)
        inserted_count += len(batch)

    print(
        f"[OK] Room {room_id} sensor {sensor_id} ({sensor_type}) "
        f"backfilled with {inserted_count} points"
    )
    return inserted_count


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill the TimeSeries DB with one year of historical sensor data for every room sensor."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="How many days of history to generate.",
    )
    parser.add_argument(
        "--step-seconds",
        type=int,
        default=3600,
        help="Time interval, in seconds, between generated measurements.",
    )
    parser.add_argument(
        "--catalog-url",
        default=None,
        help="Override the catalog URL. Defaults to the value in Simulation/conf.json.",
    )
    parser.add_argument(
        "--simulation-conf",
        default=os.path.join(os.path.dirname(__file__), "conf.json"),
        help="Path to Simulation/conf.json.",
    )
    parser.add_argument(
        "--time-series-conf",
        default=os.path.join(PROJECT_ROOT, "time_series", "conf.json"),
        help="Path to time_series/conf.json.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    simulation_conf = load_json_file(args.simulation_conf)
    time_series_conf = load_json_file(args.time_series_conf)
    catalog_url = args.catalog_url or simulation_conf["catalog"]["url"]
    end_dt = datetime.now().replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=args.days)

    if args.step_seconds <= 0:
        raise ValueError("--step-seconds must be greater than 0")

    points_per_sensor = count_measurements(start_dt, end_dt, args.step_seconds)
    print(
        f"Preparing historical backfill from {start_dt.isoformat()} to {end_dt.isoformat()} "
        f"every {args.step_seconds} seconds ({points_per_sensor} points per sensor)."
    )

    user_service_url = get_user_service_endpoint(catalog_url)
    rooms = fetch_all_rooms(user_service_url)
    if not rooms:
        print("No rooms found. Nothing to backfill.")
        return

    mongo_db = create_time_series_db(time_series_conf)
    if not mongo_db.health_check():
        raise RuntimeError("Unable to connect to TimeSeries MongoDB")

    measurements = mongo_db.db["measurements"]

    total_rooms = 0
    total_sensors = 0
    total_points = 0

    try:
        for room in rooms:
            room_id = room.get("id")
            if room_id is None:
                continue

            sensors = build_simulated_room_sensors(room, simulation_conf)

            total_rooms += 1
            for sensor in sensors:
                total_sensors += 1
                total_points += backfill_sensor_history(
                    measurements=measurements,
                    sensor=sensor,
                    room=room,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    step_seconds=args.step_seconds,
                )
    finally:
        if getattr(mongo_db, "client_mongo", None) is not None:
            mongo_db.client_mongo.close()

    print(
        f"Completed backfill for {total_sensors} sensors across {total_rooms} rooms "
        f"with {total_points} generated measurements."
    )


if __name__ == "__main__":
    main()
