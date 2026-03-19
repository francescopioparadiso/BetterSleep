import time
import logging
import threading
import requests


class UserEntry:
    def __init__(self, house_id, active_room_id, night_time, morning_time, config,
                 live_targets, is_sleeping, phase, phase_published, start_sleep_sent,
                 sensor_ts, light, actuators_state, last_seen_monotonic):
        self.house_id       = house_id
        self.active_room_id = active_room_id
        self.night_time     = night_time
        self.morning_time   = morning_time

        self.config = config  # fixed targets from user preferences
        self.live_targets = live_targets  # overridden mid-session by PhaseManager

        self.is_sleeping      = is_sleeping
        self.phase            = phase  # DAY | WIND_DOWN | SLEEP | WAKE_UP
        self.phase_published  = phase_published
        self.start_sleep_sent = start_sleep_sent
        self.sensor_ts        = sensor_ts

        # Store actuator states and current light value in a single dictionary
        # Example: {"fan": 0, "heater": 1, "light": 50}
        self.actuators_state = actuators_state or {}
        self._last_seen      = last_seen_monotonic

    def touch(self):
        self._last_seen = time.monotonic()

    def is_stale(self, ttl):
        return (time.monotonic() - self._last_seen) > ttl

    @property
    def last_seen_monotonic(self):
        return self._last_seen

    def get_actuator_state(self, actuator_type):
        return self.actuators_state.get(actuator_type)

    def set_actuator_state(self, actuator_type, value):
        self.actuators_state[actuator_type] = value

    def get_light(self):
        return self.actuators_state.get("light")

    def set_light(self, value):
        self.actuators_state["light"] = value


class UserCache:
    TTL_SECONDS       = 7200
    EVICTION_INTERVAL = 300

    def __init__(self, user_service_endpoint, catalog_url, room_to_user_map,
                 ttl_seconds=TTL_SECONDS, eviction_interval=EVICTION_INTERVAL, logger=None):
        self._user_endpoint     = user_service_endpoint
        self._catalog_url       = catalog_url
        self._room_to_user      = room_to_user_map  # shared dict owned by orchestrator
        self._ttl               = ttl_seconds
        self._eviction_interval = eviction_interval
        self.logger             = logger or logging.getLogger(__name__)

        self._lock = threading.RLock()
        self._data: dict[str, UserEntry] = {}

    # ------------------------------------------------------------------
    # Public read / write API
    # ------------------------------------------------------------------

    def get(self, userid):
        return self._data.get(userid)

    def get_or_fetch(self, userid):
        return self._data.get(userid) or self._fetch(userid)

    def touch(self, userid):
        entry = self._data.get(userid)
        if entry:
            entry.touch()

    def patch_preferences(self, userid, updates):
        """Apply schedule key updates (night_time / morning_time) without a full re-fetch."""
        with self._lock:
            entry = self._data.get(userid)
            if not entry:
                return False
            for key, value in updates.items():
                if hasattr(entry, key):
                    setattr(entry, key, value)
                    self.logger.info(f"Preference updated: user={userid} {key}={value}")
            return True

    # ------------------------------------------------------------------
    # Actuator management
    # ------------------------------------------------------------------

    def get_actuators_for_room(self, room_id):
        """Return actuator types for a room, fetching from catalog on first call."""
        entry = self._entry_for_room(room_id)
        if not entry:
            return []
        # If no actuator types are stored, fetch and initialize them
        if not entry.actuators_state.get("_types_fetched", False):
            fetched = self._fetch_actuators(room_id)
            for actuator_type in fetched:
                if actuator_type not in entry.actuators_state:
                    entry.actuators_state[actuator_type] = 0  # Default state
            entry.actuators_state["_types_fetched"] = True
            self.logger.info(f"Actuators lazy-fetched for room {room_id}: {fetched}")
        # Return all actuator types except special keys
        return [k for k in entry.actuators_state.keys() if k not in ("_types_fetched", "light")]

    def add_actuator(self, room_id, actuator_type):
        entry = self._entry_for_room(room_id)
        if entry and actuator_type not in entry.actuators_state:
            entry.actuators_state[actuator_type] = 0  # Default state
            entry.actuators_state["_types_fetched"] = True
            self.logger.info(f"Actuator added: room={room_id} type={actuator_type}")

    def remove_actuator(self, room_id, actuator_type):
        entry = self._entry_for_room(room_id)
        if entry and actuator_type in entry.actuators_state:
            del entry.actuators_state[actuator_type]
            self.logger.info(f"Actuator removed: room={room_id} type={actuator_type}")

    def invalidate_actuators(self, room_id):
        """Force a re-fetch on the next get_actuators_for_room call."""
        entry = self._entry_for_room(room_id)
        if entry:
            # Remove all actuator types except special keys
            keys_to_remove = [k for k in entry.actuators_state.keys() if k not in ("light",)]
            for k in keys_to_remove:
                del entry.actuators_state[k]
            entry.actuators_state["_types_fetched"] = False
            self.logger.info(f"Actuator cache invalidated for room {room_id}")

    # ------------------------------------------------------------------
    # Room association seeding & eviction
    # ------------------------------------------------------------------

    def seed_room_associations(self):
        """Populate the room→user map from the user-service at startup."""
        try:
            res = requests.get(f"{self._user_endpoint}/getActiveRoomsWithUser")
            if res.status_code != 200:
                self.logger.error(f"Failed to seed room associations: {res.status_code}")
                return
            mapping = {
                str(room_id): user_id
                for user_id, room_id in res.json().get("active_rooms", {}).items()
            }
        except Exception as e:
            self.logger.error(f"Exception seeding room associations: {e}")
            return

        with self._lock:
            self._room_to_user.update(mapping)
        self.logger.info(f"Room→user map seeded: {mapping}")

    def start_eviction_loop(self):
        threading.Thread(target=self._eviction_loop, daemon=True, name="cache-eviction").start()
        self.logger.info(
            f"Cache eviction loop started (TTL={self._ttl}s, interval={self._eviction_interval}s)"
        )

    def _entry_for_room(self, room_id):
        userid = self._room_to_user.get(room_id)
        return self._data.get(userid) if userid else None

    def _eviction_loop(self):
        while True:
            time.sleep(self._eviction_interval)
            try:
                self._evict_stale()
            except Exception as e:
                self.logger.error(f"[EVICTION] Unexpected error: {e}")

    def _evict_stale(self):
        with self._lock:
            stale = [uid for uid, e in self._data.items() if e.is_stale(self._ttl)]
            for uid in stale:
                room_id = self._data.pop(uid).active_room_id
                self._room_to_user.pop(room_id, None)
        if stale:
            self.logger.info(f"[EVICTION] Evicted {len(stale)} user(s): {stale}")

    def _fetch(self, userid):
        pref = self._fetch_preferences(userid)
        if pref is None:
            return None

        r_id     = pref.get("room_id")
        previous = self._data.get(userid)

        # Drop stale room mapping when the user's active room has changed
        if previous and previous.active_room_id and previous.active_room_id != r_id:
            if self._room_to_user.get(previous.active_room_id) == userid:
                del self._room_to_user[previous.active_room_id]

        def prev(attr, fallback=None):
            return getattr(previous, attr, fallback) if previous else fallback

        is_sleeping = pref.get("is_sleeping", prev("is_sleeping", False))

        # Build actuators_state dict
        actuators_state = {}
        # If previous entry exists, copy its actuators_state
        if previous and hasattr(previous, "actuators_state"):
            actuators_state = dict(previous.actuators_state)
        # Set current light value if available
        if prev("light") is not None:
            actuators_state["light"] = prev("light")

        entry = UserEntry(
            house_id       = pref.get("house_id"),
            active_room_id = r_id,
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
            phase_published   = prev("phase_published",  False),
            start_sleep_sent  = prev("start_sleep_sent", False),
            sensor_ts         = prev("sensor_ts"),
            light             = None,  # Now stored in actuators_state
            actuators_state   = actuators_state,
            last_seen_monotonic = prev("last_seen_monotonic", time.monotonic()),
        )

        with self._lock:
            self._data[userid]       = entry
            self._room_to_user[r_id] = userid

        return entry

    def _fetch_preferences(self, userid):
        try:
            res = requests.get(
                f"{self._user_endpoint}/getUserRoomPreferences",
                params={"user_id": userid},
            )
        except requests.RequestException as e:
            self.logger.error(f"Network error fetching preferences for {userid}: {e}")
            return None

        if res.status_code != 200:
            self.logger.error(f"HTTP {res.status_code} fetching preferences for {userid}")
            return None

        pref = res.json().get("preferences", {})
        return pref.get("user_preferences", pref)

    def _fetch_actuators(self, room_id):
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
            print(f"Raw actuator response for room {room_id}: {res.text}")
            return list({
                str(a["type"]).lower()
                for a in res.json().get("actuators", []) if a.get("type")
            })
        except Exception as e:
            self.logger.error(f"Error decoding actuator response for room {room_id}: {e}")
            return []