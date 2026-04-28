import time
import logging
import threading
import requests
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserEntry:
    house_id: Any
    active_room_id: Any
    night_time: Any
    morning_time: Any
    config: dict
    live_targets: dict
    is_sleeping: bool
    phase: str  # DAY | WIND_DOWN | SLEEP | WAKE_UP
    phase_published: bool
    start_sleep_sent: bool
    sensor_ts: Any
    actuators_state: dict = field(default_factory=dict)
    last_seen_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.actuators_state = dict(self.actuators_state or {})
        if self.last_seen_monotonic is None:
            self.last_seen_monotonic = time.monotonic()

    def touch(self):
        self.last_seen_monotonic = time.monotonic()

    def is_stale(self, ttl):
        return (time.monotonic() - self.last_seen_monotonic) > ttl



class UserCache:
    TTL_SECONDS       = 7200 
    EVICTION_INTERVAL = 300
    _ACTUATOR_TYPES_FETCHED_KEY = "_types_fetched"
    _ACTUATOR_TYPES_EXCLUDED = {"light", _ACTUATOR_TYPES_FETCHED_KEY}

    def __init__(self, user_service_endpoint, catalog_url, room_to_user_map,
                 ttl_seconds=TTL_SECONDS, eviction_interval=EVICTION_INTERVAL, logger=None):
        self._user_endpoint     = user_service_endpoint
        self._catalog_url       = catalog_url
        self._room_to_user      = room_to_user_map  # shared dict owned by orchestrator
        self._ttl               = ttl_seconds
        self._eviction_interval = eviction_interval
        self.logger             = logger or logging.getLogger(__name__)

        self._lock = threading.RLock()
        self._user_cache: dict[str, UserEntry] = {}

    @staticmethod
    def _normalize_id(value):
        return str(value) if value is not None else None

    def get_user_entry(self, user_id):
        user_id = self._normalize_id(user_id)
        if not user_id:
            return None
        return self._user_cache.get(user_id)

    def get(self, userid):
        return self.get_user_entry(userid)

    def get_or_fetch_user(self, user_id):
        user_id = self._normalize_id(user_id)
        if not user_id:
            return None
        return self._user_cache.get(user_id) or self._fetch(user_id)

    def refresh_user_entry(self, user_id):
        """Force a refresh from user-service and overwrite local cache entry."""
        user_id = self._normalize_id(user_id)
        if not user_id:
            return None
        return self._fetch(user_id)

    def touch_user(self, user_id):
        user_id = self._normalize_id(user_id)
        if not user_id:
            return
        entry = self._user_cache.get(user_id)
        if entry:
            entry.touch()

    def update_schedule_preferences(self, user_id, updates):
        """Apply schedule key updates (night_time / morning_time) without a full re-fetch."""
        user_id = self._normalize_id(user_id)
        if not user_id:
            return False
        with self._lock:
            entry = self._user_cache.get(user_id)
            if not entry:
                return False
            for key, value in updates.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
                    self.logger.info(f"Preference updated: user={user_id} {key}={value}")
            return True

    def update_room_preferences(self, user_id, room_id, house_id, updates):
        """Apply room-level preference updates and keep room->user association aligned."""
        user_id = self._normalize_id(user_id)
        room_id = self._normalize_id(room_id)
        house_id = self._normalize_id(house_id)
        if not user_id:
            return False

        with self._lock:
            entry = self._user_cache.get(user_id)
            if not entry:
                return False

            if entry.active_room_id and entry.active_room_id != room_id:
                self._room_to_user.pop(self._normalize_id(entry.active_room_id), None)

            entry.active_room_id = room_id or entry.active_room_id
            entry.house_id = house_id or entry.house_id

            room_cfg_keys = {
                "temperature_night",
                "temperature_morning",
                "light_night",
                "light_morning",
            }
            for key in room_cfg_keys:
                if key in updates:
                    entry.config[key] = float(updates[key])

            if room_id:
                self._room_to_user[room_id] = user_id
            entry.touch()
            return True

    def list_room_actuator_types(self, room_id):
        """Return actuator types for a room, fetching from catalog on first call."""
        entry = self._entry_for_room(room_id)
        if not entry:
            return []
        if not entry.actuators_state.get(self._ACTUATOR_TYPES_FETCHED_KEY, False):
            fetched = self._get_actuators(room_id)
            for actuator_type in fetched:
                if actuator_type not in entry.actuators_state:
                    entry.actuators_state[actuator_type] = 0
            entry.actuators_state[self._ACTUATOR_TYPES_FETCHED_KEY] = True
            self.logger.info(f"Actuators lazy-fetched for room {room_id}: {fetched}")
        return [k for k in entry.actuators_state.keys() if k not in self._ACTUATOR_TYPES_EXCLUDED]

    def register_room_actuator(self, room_id, actuator_type):
        """Add a new actuator type to the room entry if it does not already exist."""
        entry = self._entry_for_room(room_id)
        if entry and actuator_type not in entry.actuators_state:
            entry.actuators_state[actuator_type] = 0
            entry.actuators_state[self._ACTUATOR_TYPES_FETCHED_KEY] = True
            self.logger.info(f"Actuator added: room={room_id} type={actuator_type}")

    def remove_room_actuator(self, room_id, actuator_type):
        entry = self._entry_for_room(room_id)
        if entry and actuator_type in entry.actuators_state:
            del entry.actuators_state[actuator_type]
            self.logger.info(f"Actuator removed: room={room_id} type={actuator_type}")

    def invalidate_room_actuator_cache(self, room_id):
        """Force a re-fetch on the next room actuator lookup."""
        entry = self._entry_for_room(room_id)
        if entry:
            keys_to_remove = [k for k in entry.actuators_state.keys() if k not in ("light",)]
            for k in keys_to_remove:
                del entry.actuators_state[k]
            entry.actuators_state[self._ACTUATOR_TYPES_FETCHED_KEY] = False
            self.logger.info(f"Actuator cache invalidated for room {room_id}")

    def seed_room_user_map(self):
        """Populate the room→user map from the user-service at startup."""
        try:
            res = requests.get(f"{self._user_endpoint}/getActiveRoomsWithUser")
            if res.status_code != 200:
                self.logger.error(f"Failed to seed room associations: {res.status_code}")
                return
            mapping = {
                str(room_id): str(user_id)
                for user_id, room_id in res.json().get("active_rooms", {}).items()
            }
        except Exception as e:
            self.logger.error(f"Exception seeding room associations: {e}")
            return

        with self._lock:
            self._room_to_user.update(mapping)
        self.logger.info(f"Room→user map seeded: {mapping}")

    def start_cache_eviction_loop(self):
        threading.Thread(target=self._eviction_loop, daemon=True, name="cache-eviction").start()
        self.logger.info(
            f"Cache eviction loop started (TTL={self._ttl}s, interval={self._eviction_interval}s)"
        )

    def _entry_for_room(self, room_id):
        room_id = self._normalize_id(room_id)
        user_id = self._room_to_user.get(room_id)
        return self._user_cache.get(user_id) if user_id else None

    def _eviction_loop(self):
        while True:
            time.sleep(self._eviction_interval)
            try:
                self._evict_stale()
            except Exception as e:
                self.logger.error(f"[EVICTION] Unexpected error: {e}")

    def _evict_stale(self):
        with self._lock:
            stale = [uid for uid, e in self._user_cache.items() if e.is_stale(self._ttl)]
            for uid in stale:
                room_id = self._normalize_id(self._user_cache.pop(uid).active_room_id)
                self._room_to_user.pop(room_id, None)
        if stale:
            self.logger.info(f"[EVICTION] Evicted {len(stale)} user(s): {stale}")

    def _fetch(self, user_id):
        user_id = self._normalize_id(user_id)
        if not user_id:
            return None

        pref = self._get_preferences(user_id)
        if pref is None:
            return None

        room_id  = self._normalize_id(pref.get("room_id"))
        previous = self._user_cache.get(user_id)

        if previous and previous.active_room_id and previous.active_room_id != room_id:
            prev_room_id = self._normalize_id(previous.active_room_id)
            if self._room_to_user.get(prev_room_id) == user_id:
                del self._room_to_user[prev_room_id]

        def prev(attr, fallback=None):
            return getattr(previous, attr, fallback) if previous else fallback

        is_sleeping = pref.get("is_sleeping", prev("is_sleeping", False))
        previous_last_seen = prev("last_seen_monotonic", time.monotonic())
        last_seen_monotonic = (
            float(previous_last_seen)
            if isinstance(previous_last_seen, (int, float))
            else time.monotonic()
        )

        actuators_state = {}
        if previous and hasattr(previous, "actuators_state"):
            actuators_state = dict(previous.actuators_state)
        entry = UserEntry(
            house_id       = pref.get("house_id"),
            active_room_id = room_id,
            night_time     = pref.get("night_time"),
            morning_time   = pref.get("morning_time"),
            config = {
                "temperature_night":   float(pref.get("temperature_night",   18.0)),
                "temperature_morning": float(pref.get("temperature_morning", 22.0)),
                "light_night":         float(pref.get("light_night",          0.0)),
                "light_morning":       float(pref.get("light_morning",       100.0)),
            },
            live_targets = {
                "temperature": prev("live_targets", {}).get("temperature"),
                "light":       prev("live_targets", {}).get("light"),
            },
            is_sleeping       = is_sleeping,
            phase             = "SLEEP" if is_sleeping else "DAY",
            phase_published   = bool(prev("phase_published",  False)),
            start_sleep_sent  = bool(prev("start_sleep_sent", False)),
            sensor_ts         = prev("sensor_ts"),
            actuators_state   = actuators_state,
            last_seen_monotonic = last_seen_monotonic,
        )

        with self._lock:
            self._user_cache[user_id] = entry
            if room_id:
                self._room_to_user[room_id] = user_id

        return entry

    def _get_preferences(self, user_id):
        try:
            res = requests.get(
                f"{self._user_endpoint}/getUserRoomPreferences",
                params={"user_id": user_id},
            )
        except requests.RequestException as e:
            self.logger.error(f"Network error fetching preferences for {user_id}: {e}")
            return None

        if res.status_code != 200:
            self.logger.error(f"HTTP {res.status_code} fetching preferences for {user_id}")
            return None

        pref = res.json().get("preferences", {})
        return pref.get("user_preferences", pref)

    def _get_actuators(self, room_id):
        try:
            res = requests.get(
                f"{self._catalog_url}/getActuatorByRoom",
                params={"room_id": room_id},
            )
        except requests.RequestException as e:
            self.logger.error(f"Network error fetching actuators for room {room_id}: {e}")
            return []

        if res.status_code != 200:
            self.logger.error(f"HTTP {res.status_code} fetching actuators for room {room_id}")
            return []

        try:
            self.logger.debug(f"Raw actuator response for room {room_id}: {res.text}")
            return list({
                str(a["type"]).lower()
                for a in res.json().get("actuators", []) if a.get("type")
            })
        except Exception as e:
            self.logger.error(f"Error decoding actuator response for room {room_id}: {e}")
            return []
