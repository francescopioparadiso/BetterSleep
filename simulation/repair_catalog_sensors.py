import argparse
import json
from datetime import datetime
from pathlib import Path

import requests
from pymongo import MongoClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
USER_SERVICE_CONF = PROJECT_ROOT / "user_service" / "conf.json"
CATALOG_CONF = PROJECT_ROOT / "catalog" / "conf.json"
DEFAULT_ROOM_SENSOR_TYPES = {
    "ambient_temp",
    "light",
    "humidity",
    "heart_rate",
    "vibration",
    "presence",
}


def load_json(path):
    return json.loads(path.read_text())


def build_user_service_url():
    conf = load_json(USER_SERVICE_CONF)
    host = conf["serviceInfo"]["host"].replace("0.0.0.0", "127.0.0.1")
    port = conf["serviceInfo"]["port"]
    return f"http://{host}:{port}"


def fetch_valid_rooms():
    response = requests.get(f"{build_user_service_url()}/getAllRooms", timeout=10)
    response.raise_for_status()
    rooms = response.json().get("rooms", [])
    return {str(room["id"]): room for room in rooms if room.get("id") is not None}


def open_catalog_collection():
    conf = load_json(CATALOG_CONF)["database"]
    client = MongoClient(
        host=conf["host"],
        port=conf["port"],
        username=conf["username"],
        password=conf["password"],
        serverSelectionTimeoutMS=5000,
    )
    db = client[conf["database"]]
    return client, db.sensors


def format_last_update(value):
    if isinstance(value, str):
        return value
    try:
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(value)


def looks_like_legacy_room_sensor(doc):
    sensor_type = doc.get("type")
    sensor_id = doc.get("sensorID")
    endpoint = doc.get("endpoint", "")

    if sensor_type not in DEFAULT_ROOM_SENSOR_TYPES:
        return False
    if endpoint not in ("", None):
        return False
    if isinstance(sensor_id, str) and sensor_id.startswith("sensor_"):
        return False

    try:
        int(sensor_id)
        return True
    except (TypeError, ValueError):
        return False


def repair_document(doc, room):
    room_id = str(room["id"])
    house_id = str(room["house_id"])
    sensor_type = doc["type"]
    return {
        "sensorID": f"sensor_{house_id}_{room_id}_{sensor_type}",
        "roomID": room_id,
        "houseID": house_id,
        "endpoint": "",
        "last_update": format_last_update(doc.get("last_update")),
        "persistent": True,
    }


def main():
    parser = argparse.ArgumentParser(description="Repair legacy/orphan catalog sensor documents.")
    parser.add_argument("--apply", action="store_true", help="Apply changes instead of printing the plan.")
    args = parser.parse_args()

    valid_rooms = fetch_valid_rooms()
    client, sensors = open_catalog_collection()

    deleted = 0
    updated = 0
    try:
        for doc in sensors.find({}):
            room_id = doc.get("roomID")
            room_key = str(room_id) if room_id is not None else None
            room = valid_rooms.get(room_key)

            if room is None:
                action = f"DELETE orphan sensor {doc.get('sensorID')} (roomID={room_id})"
                print(action)
                if args.apply:
                    sensors.delete_one({"_id": doc["_id"]})
                    deleted += 1
                continue

            if not looks_like_legacy_room_sensor(doc):
                continue

            repaired = repair_document(doc, room)
            action = (
                f"UPDATE sensor {doc.get('sensorID')} -> {repaired['sensorID']} "
                f"(roomID={room_key})"
            )
            print(action)
            if args.apply:
                sensors.update_one(
                    {"_id": doc["_id"]},
                    {
                        "$set": repaired,
                        "$unset": {"mqtt_topic": ""},
                    },
                )
                updated += 1
    finally:
        client.close()

    if args.apply:
        print(f"[DONE] deleted={deleted}, updated={updated}")
    else:
        print("[DRY RUN] Re-run with --apply to persist the changes.")


if __name__ == "__main__":
    main()
