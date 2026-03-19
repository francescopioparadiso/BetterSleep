import time
import logging
import threading
import requests
from dataclasses import dataclass, field


@dataclass
class UserEntry:
    # Identity
    house_id:       str | None
    active_room_id: str | None

    # Schedule strings from the user-service
    night_time:   str | None
    morning_time: str | None

    # Fixed targets from preferences
    config: dict = field(default_factory=lambda: {
        "temperature_night":   18.0,
        "temperature_morning": 22.0,
        "light_night":          0.0,
        "light_morning":       100.0,
    })

    # Dynamic targets set by PhaseManager mid-session
    live_targets: dict = field(default_factory=lambda: {
        "temperature": None,
        "light":       None,
    })

    # Sensor / phase state
    is_sleeping:      bool  = False
    phase:            str   = "DAY"      # DAY | WIND_DOWN | SLEEP | WAKE_UP
    phase_published:  bool  = False
    start_sleep_sent: bool  = False
    sensor_ts:        int | None = None
    light:            float | None = None   # last measured lux

    # Actuator types present in the active room  (merged from ActuatorRegistry)
    # Empty list means "not yet fetched" — UserCache.get_actuators_for_room fetches lazily.
    actuators: list[str] = field(default_factory=list)
    _actuators_fetched: bool = False

    # Eviction
    _last_seen_monotonic: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self._last_seen_monotonic = time.monotonic()

    def is_stale(self, ttl: float) -> bool:
        return (time.monotonic() - self._last_seen_monotonic) > ttl

    @property
    def last_seen_monotonic(self):
        return self._last_seen_monotonic

    @property
    def actuators_fetched(self):
        return self._actuators_fetched


class UserCache:
    _DEFAULT_TTL_SECONDS       = 7200
    _DEFAULT_EVICTION_INTERVAL = 300

    def __init__(
        self,
        user_service_endpoint: str,
        catalog_url:           str,
        room_to_user_map:      dict,   # shared mutable dict owned by the orchestrator
        ttl_seconds:           int = _DEFAULT_TTL_SECONDS,
        eviction_interval:     int = _DEFAULT_EVICTION_INTERVAL,
        logger: logging.Logger = None,
    ):
        self._user_endpoint     = user_service_endpoint
        self._catalog_url       = catalog_url
        self._room_to_user      = room_to_user_map
        self._ttl               = ttl_seconds
        self._eviction_interval = eviction_interval
        self.logger             = logger or logging.getLogger(__name__)

        self._lock = threading.RLock()
        self._data: dict[str, UserEntry] = {}


    def get(self, userid: str) -> UserEntry | None:
        return self._data.get(userid)

    def get_or_fetch(self, userid: str) -> UserEntry | None:
        return self._data.get(userid) or self._fetch(userid)

    def touch(self, userid: str) -> None:
        entry = self._data.get(userid)
        if entry:
            entry.touch()

    def patch_preferences(self, userid: str, updates: dict) -> bool:
        """Update schedule keys (night_time / morning_time) in place."""
        with self._lock:
            entry = self._data.get(userid)
            if not entry:
                return False
            for k, v in updates.items():
                if hasattr(entry, k):
                    setattr(entry, k, v)
                    self.logger.info(f"Preference updated: user={userid} {k}={v}")
            return True


    def get_actuators_for_room(self, room_id: str) -> list[str]:
        """Return actuator list, fetching from catalog lazily on first call."""
        entry = self._entry_for_room(room_id)
        if not entry:
            return []
        if not entry.actuators_fetched:
            fetched = self._fetch_actuators(room_id)
            entry.actuators          = fetched
            entry._actuators_fetched = True
            self.logger.info(f"Actuators lazy-fetched for room {room_id}: {fetched}")
        return entry.actuators

    def add_actuator(self, room_id: str, actuator_type: str) -> None:
        entry = self._entry_for_room(room_id)
        if entry and actuator_type not in entry.actuators:
            entry.actuators.append(actuator_type)
            entry._actuators_fetched = True
            self.logger.info(f"Actuator added: room={room_id} type={actuator_type}")

    def remove_actuator(self, room_id: str, actuator_type: str) -> None:
        entry = self._entry_for_room(room_id)
        if entry and actuator_type in entry.actuators:
            entry.actuators.remove(actuator_type)
            self.logger.info(f"Actuator removed: room={room_id} type={actuator_type}")

    def invalidate_actuators(self, room_id: str) -> None:
        """Force a re-fetch on next get_actuators_for_room call."""
        entry = self._entry_for_room(room_id)
        if entry:
            entry.actuators          = []
            entry._actuators_fetched = False
            self.logger.info(f"Actuator cache invalidated for room {room_id}")

    def _entry_for_room(self, room_id: str) -> UserEntry | None:
        userid = self._room_to_user.get(room_id)
        return self._data.get(userid) if userid else None

    def seed_room_associations(self) -> None:
        """Populate room→user map from the user-service at startup."""
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

    def start_eviction_loop(self) -> None:
        threading.Thread(
            target=self._eviction_loop, daemon=True, name="cache-eviction"
        ).start()
        self.logger.info(
            f"Cache eviction loop started "
            f"(TTL={self._ttl}s, interval={self._eviction_interval}s)"
        )

    def _eviction_loop(self) -> None:
        while True:
            time.sleep(self._eviction_interval)
            try:
                self._evict_stale()
            except Exception as e:
                self.logger.error(f"[EVICTION] Unexpected error: {e}")

    def _evict_stale(self) -> None:
        with self._lock:
            stale = [uid for uid, e in self._data.items() if e.is_stale(self._ttl)]
            for uid in stale:
                room_id = self._data.pop(uid).active_room_id
                self._room_to_user.pop(room_id, None)

        if stale:
            self.logger.info(f"[EVICTION] Evicted {len(stale)} user(s): {stale}")


    def _fetch(self, userid: str) -> UserEntry | None:
        pref = self._fetch_preferences(userid)
        if pref is None:
            return None

        r_id     = pref.get("room_id")
        previous = self._data.get(userid)

        # Clean up stale room mapping when active room changes
        if previous and previous.active_room_id and previous.active_room_id != r_id:
            if self._room_to_user.get(previous.active_room_id) == userid:
                del self._room_to_user[previous.active_room_id]

        entry = UserEntry(
            house_id         = pref.get("house_id"),
            active_room_id   = r_id,
            night_time       = pref.get("night_time"),
            morning_time     = pref.get("morning_time"),
            config = {
                "temperature_night":   float(pref.get("temperature_night",   18.0)),
                "temperature_morning": float(pref.get("temperature_morning", 22.0)),
                "light_night":         float(pref.get("light_night",          0.0)),
                "light_morning":       float(pref.get("light_morning",       100.0)),
            },
            live_targets = {
                "temperature": previous.live_targets.get("temperature") if previous else None,
                "light":       previous.live_targets.get("light")       if previous else None,
            },
            is_sleeping      = pref.get("is_sleeping", previous.is_sleeping if previous else False),
            phase            = "SLEEP" if pref.get("is_sleeping", False) else "DAY",
            phase_published  = previous.phase_published  if previous else False,
            start_sleep_sent = previous.start_sleep_sent if previous else False,
            sensor_ts        = previous.sensor_ts        if previous else None,
            light            = previous.light            if previous else None,
            actuators            = [],
            _actuators_fetched   = False,
            _last_seen_monotonic = previous.last_seen_monotonic if previous else time.monotonic(),
        )

        with self._lock:
            self._data[userid]       = entry
            self._room_to_user[r_id] = userid

        return entry

    def _fetch_preferences(self, userid: str) -> dict | None:
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

    def _fetch_actuators(self, room_id: str) -> list[str]:
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
            types = list({
                str(a["type"]).lower()
                for a in res.json().get("actuators", []) if a.get("type")
            })
            self.logger.info(f"Fetched actuators for room {room_id}: {types}")
            return types
        except Exception as e:
            self.logger.error(f"Error decoding actuator response for room {room_id}: {e}")
            return []

