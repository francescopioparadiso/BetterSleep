import json
import os
import sys
import time
import logging
import threading
import cherrypy
import requests
import re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from datetime import datetime

from common.common import mqtt_to_regex, json_error_page
from PhaseManager import PhaseManager


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _resolve_temperature_action(temp_value, desired_temperature, room_actuators,
                                 prefer_fan=True, tolerance=0.0):
    """
    Called only when temp is OUTSIDE the deadband (caller handles in-band).
    prefer_fan=False (SLEEP phase) avoids turning on the fan to reduce noise.
    """
    temp_value          = float(temp_value)
    desired_temperature = float(desired_temperature)
    tol                 = max(0.0, float(tolerance))

    too_hot = temp_value > desired_temperature + tol
    too_cold = temp_value < desired_temperature - tol

    if too_hot:
        if prefer_fan and "fan" in room_actuators:
            return 1, "fan"
        if "heater" in room_actuators:
            return 0, "heater"
        if "fan" in room_actuators:       # fallback even if not preferred
            return 1, "fan"

    if too_cold:
        if "heater" in room_actuators:
            return 1, "heater"
        if "fan" in room_actuators:       # turn fan off if it was running
            return 0, "fan"

    return None, None


def _parse_preference_topic(topic):
    parts = topic.split("/")
    # UserService/ChangePreference/User/{userid}/Preference/
    if len(parts) >= 5 and parts[2] == "User":
        return "user", parts[3]
    # UserService/ChangePreference/House/{houseID}/Bedroom/{bedroomid}/User/{userid}/Preference/
    if len(parts) >= 8 and parts[2] == "House":
        return "room", parts[5]
    return None, None


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class SleepCycleManager:
    exposed = True

    # Defaults — overridden by conf.json keys below
    _DEFAULT_SLEEP_DETECTION_SECONDS   = 1800   # 30 min in bed  -> mark sleeping
    _DEFAULT_WAKE_DETECTION_SECONDS    = 300    # 5 min out of bed -> finish sleep
    _DEFAULT_USER_CACHE_TTL_SECONDS    = 7200   # 2 h idle        -> evict from cache
    _DEFAULT_EVICTION_INTERVAL_SECONDS = 300    # run eviction every 5 min

    def __init__(self, conf, logger=None):
        self.mqtt_client = None
        self.logger      = logger or logging.getLogger(__name__)

        self.catalog_url     = conf['catalogURL']
        self.service_info    = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)

        self.catalog_client = CatalogClient(
            self.catalog_url, self.service_info, self.remove_interval
        )
        self.catalog_client.register()

        self.MQTT_info             = conf['MQTT']
        self.user_service_endpoint = self._get_endpoint_user_service()
        self.topic_subscribe_raw   = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [
            re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw
        ]
        self.topic_publish = self.MQTT_info.get('topic_publish')

        self.temperature_tolerance     = float(conf.get('temperatureTolerance', 0.5))
        self.SLEEP_DETECTION_SECONDS   = int(conf.get('sleepDetectionSec',   self._DEFAULT_SLEEP_DETECTION_SECONDS))
        self.WAKE_DETECTION_SECONDS    = int(conf.get('wakeDetectionSec',    self._DEFAULT_WAKE_DETECTION_SECONDS))
        self.USER_CACHE_TTL_SECONDS    = int(conf.get('userCacheTTLSec',     self._DEFAULT_USER_CACHE_TTL_SECONDS))
        self.EVICTION_INTERVAL_SECONDS = int(conf.get('evictionIntervalSec', self._DEFAULT_EVICTION_INTERVAL_SECONDS))

        # userid  -> user data dict
        self.active_users_cache: dict = {}
        # room_id -> userid  (derived index, kept in sync)
        self.room_to_user_map:   dict = {}
        # room_id -> list[str] of actuator types  (lazy, cleared on user eviction)
        self._actuator_cache:    dict = {}

        self.phase_manager = PhaseManager(
            manager_instance=self,
            transition_window_min=conf.get('transitionWindowMin', 30),
            check_interval=conf.get('phaseCheckIntervalSec', 60),
            transition_curve_exponent=conf.get('transitionCurveExponent', 1.0),
        )

        self._init_mqtt_client()
        self.get_active_room_for_user()
        self._start_eviction_loop()

    # ------------------------------------------------------------------
    # Startup helpers
    # ------------------------------------------------------------------

    def _get_endpoint_user_service(self):
        data, status, error = self.catalog_client.get("getEndpointUserService")
        endpoint = (data or {}).get("endpoint") if status == 200 else None
        if endpoint:
            self.logger.info(f"User service endpoint retrieved: {endpoint}")
            return endpoint
        self.logger.error(f"Error retrieving user service endpoint: {status} - {error}")
        return None

    def get_active_room_for_user(self):
        """Fetch active user->room associations and populate room_to_user_map."""
        try:
            res = requests.get(f"{self.user_service_endpoint}/getActiveRoomsWithUser")
            if res.status_code != 200:
                self.logger.error(f"Failed to sync associations: {res.status_code}")
                return
            # user service returns {user_id: room_id}, we need {room_id: user_id}
            self.room_to_user_map = {
                str(room_id): user_id
                for user_id, room_id in res.json().get("active_rooms", {}).items()
            }
            self.logger.info(f"Association map synchronised: {self.room_to_user_map}")
        except Exception as e:
            self.logger.error(f"Exception during association sync: {e}")

    # ------------------------------------------------------------------
    # Cache eviction
    # ------------------------------------------------------------------

    def _start_eviction_loop(self):
        threading.Thread(
            target=self._eviction_loop, daemon=True, name="cache-eviction"
        ).start()
        self.logger.info(
            f"Cache eviction loop started "
            f"(TTL={self.USER_CACHE_TTL_SECONDS}s, interval={self.EVICTION_INTERVAL_SECONDS}s)"
        )

    def _eviction_loop(self):
        while True:
            time.sleep(self.EVICTION_INTERVAL_SECONDS)
            try:
                self._evict_stale_users()
            except Exception as e:
                self.logger.error(f"[EVICTION] Unexpected error: {e}")

    def _evict_stale_users(self):
        now      = time.monotonic()
        to_evict = [
            uid for uid, data in self.active_users_cache.items()
            if (now - data.get("_last_seen_monotonic", 0)) > self.USER_CACHE_TTL_SECONDS
        ]
        for uid in to_evict:
            room_id = self.active_users_cache.pop(uid).get("active_room_id")
            self.room_to_user_map.pop(room_id, None)
            self._actuator_cache.pop(room_id, None)
        if to_evict:
            self.logger.info(f"[EVICTION] Evicted {len(to_evict)} user(s): {to_evict}")

    # ------------------------------------------------------------------
    # User preference cache
    # ------------------------------------------------------------------

    def _fetch_and_cache_room_preference(self, userid):
        """
        Fetch user preferences from the user service and store them in cache.
        Returns the cache entry on success, None on any failure.
        """
        try:
            res = requests.get(
                f"{self.user_service_endpoint}/getUserRoomPreferences",
                params={"user_id": userid},
            )
        except requests.RequestException as e:
            self.logger.error(f"Network error fetching preferences for {userid}: {e}")
            return None

        if res.status_code != 200:
            self.logger.error(f"HTTP {res.status_code} fetching preferences for {userid}")
            return None

        pref = res.json().get("preferences", {})
        # Backward compatibility with nested response shape
        pref = pref.get("user_preferences", pref)

        r_id     = pref.get("room_id")
        previous = self.active_users_cache.get(userid, {})
        prev_lv  = previous.get("live_values", {})
        prev_lt  = previous.get("live_targets", {})

        # If the user moved rooms, clean up the old mapping and actuator cache
        old_room = previous.get("active_room_id")
        if old_room and old_room != r_id:
            if self.room_to_user_map.get(old_room) == userid:
                del self.room_to_user_map[old_room]
            self._actuator_cache.pop(old_room, None)

        entry = {
            "active_room_id": r_id,
            "house_id":       pref.get("house_id"),
            "night_time":     pref.get("night_time"),
            "morning_time":   pref.get("morning_time"),
            "is_sleeping":    pref.get("is_sleeping", previous.get("is_sleeping", False)),
            "config": {
                "temperature_night":   float(pref.get("temperature_night",   18.0)),
                "temperature_morning": float(pref.get("temperature_morning", 22.0)),
                "light_night":         float(pref.get("light_night",          0.0)),
                "light_morning":       float(pref.get("light_morning",       100.0)),
            },
            "live_targets": {
                "temperature": prev_lt.get("temperature"),
                "light":       prev_lt.get("light"),
            },
            "live_values": {
                "light":            prev_lv.get("light"),
                "light_actuator":   prev_lv.get("light_actuator"),
                "heater_state":     prev_lv.get("heater_state"),
                "fan_state":        prev_lv.get("fan_state"),
                "phase":            "SLEEP" if pref.get("is_sleeping", False) else "DAY",
                "phase_published":  prev_lv.get("phase_published",  False),
                "start_sleep_sent": prev_lv.get("start_sleep_sent", False),
                "last_seen_bed":    prev_lv.get("last_seen_bed"),
                "last_left_bed":    prev_lv.get("last_left_bed"),
                "sensor_ts":        prev_lv.get("sensor_ts"),
            },
            # Initialise to now so a freshly-fetched entry is not immediately evicted
            "_last_seen_monotonic": previous.get("_last_seen_monotonic", time.monotonic()),
        }

        self.active_users_cache[userid] = entry
        self.room_to_user_map[r_id]     = userid
        return entry

    def _get_or_fetch_user(self, userid):
        """Return cached user data, fetching from user service if missing."""
        return self.active_users_cache.get(userid) or self._fetch_and_cache_room_preference(userid)

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------

    def _init_mqtt_client(self):
        try:
            self.mqtt_client = MyMQTT(
                self.MQTT_info['clientID'],
                self.MQTT_info['broker'],
                self.MQTT_info['port'],
                self,
            )
            self.mqtt_client.start()
            for topic in self.topic_subscribe_raw:
                self.mqtt_client.mySubscribe(topic)
            self.logger.info(f"MQTT client initialised and subscribed to {self.topic_subscribe_raw}")
        except Exception as e:
            self.logger.error(f"Error initialising MQTT client: {e}")
            self.catalog_client.unregister()
            sys.exit(1)

    # Keep original names so PhaseManager can call them
    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def publish(self, message, command_topic=None):
        try:
            self.mqtt_client.myPublish(command_topic, message)
            self.logger.info(f"Published to {command_topic}: {message}")
        except Exception as e:
            self.logger.error(f"Error publishing message: {e}")

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
        except json.JSONDecodeError:
            self.logger.error(f"Invalid JSON payload received on topic {topic}")
            return

        for index, regex in enumerate(self.topic_subscribe_regex):
            if not regex.match(topic):
                continue

            if index == 0:
                self._handle_sensor_topic(topic, message_received)
                return

            if index == 1:
                self._handle_actuator_topic(topic, message_received)
                return

            if index == 2:
                self._handle_preference_topic(topic, message_received)
                return

        self.logger.warning(f"Message on unrecognised topic: {topic}")

    def _handle_sensor_topic(self, topic, msg):
        # House/{houseid}/Bedroom/{roomid}/sensor/{sensor_type}/{sensorid}/data
        parts = topic.split("/")
        if len(parts) < 8:
            self.logger.warning(f"Invalid sensor topic format: {topic}")
            return

        house_id    = parts[1]
        room_id     = parts[3]
        sensor_type = parts[5]

        userid = self.room_to_user_map.get(room_id)
        if userid is None:
            self.logger.warning(
                f"[SENSOR SKIPPED] room_id={room_id!r} not in room_to_user_map "
                f"(keys: {list(self.room_to_user_map.keys())})"
            )
            return

        user_data = self._get_or_fetch_user(userid)
        if not user_data:
            return

        user_data["_last_seen_monotonic"] = time.monotonic()

        # Extract and store timestamp; sync PhaseManager clock
        ts = msg['e'][0].get('t') if msg.get('e') else None
        if ts is not None:
            user_data['live_values']['sensor_ts'] = ts
            try:
                self.logger.info(
                    f"[PHASE SYNC] user={userid} sensor_ts={ts} "
                    f"-> {datetime.fromtimestamp(float(ts)).strftime('%H:%M')}"
                )
                self.phase_manager.sync_from_sensor_time(float(ts), userid)
            except Exception as e:
                self.logger.error(f"[PHASE SYNC ERROR] {e}")
        else:
            self.logger.warning(f"[PHASE SYNC SKIPPED] no timestamp in payload for user={userid}")

        if sensor_type == "ambient_temp":
            phase        = user_data['live_values'].get('phase')
            desired_temp = user_data['live_targets']['temperature'] or (
                user_data['config']['temperature_night']
                if phase == "SLEEP"
                else user_data['config']['temperature_morning']
            )
            self._handle_temperature(msg, self._get_actuators_in_room(room_id),
                                     desired_temp, house_id, room_id)

        elif sensor_type == "presence":
            self._handle_presence(msg, userid, house_id, room_id)

        elif sensor_type == "light":
            try:
                user_data['live_values']['light'] = float(msg['e'][0]['v'])
            except Exception:
                self.logger.warning(f"Invalid light payload for user {userid}: {msg}")

    def _handle_actuator_topic(self, topic, msg):
        # House/{houseid}/Bedroom/{roomid}/actuator/{device_type}/data
        parts = topic.split("/")
        if len(parts) < 7:
            self.logger.warning(f"Invalid actuator topic format: {topic}")
            return

        room_id     = parts[3]
        device_type = parts[5]   # light | heater | fan

        userid = self.room_to_user_map.get(room_id)
        if not userid:
            return

        user_data = self._get_or_fetch_user(userid)
        if not user_data or not msg.get('e'):
            return

        value = msg['e'][0].get('v')
        key_map = {"light": "light_actuator", "heater": "heater_state", "fan": "fan_state"}
        if device_type in key_map:
            user_data['live_values'][key_map[device_type]] = value
            self.logger.info(f"Actuator {device_type} state={value} (user={userid}, room={room_id})")


    def _handle_preference_topic(self, topic, msg):
        preference_kind, entity_id = _parse_preference_topic(topic)
        if preference_kind == "user":
            self._update_user_preferences(entity_id, msg)
        else:
            self.logger.warning(f"Unhandled preference topic: {topic}")

    def _update_user_preferences(self, userid, msg):
        keys = [k for k in ("night_time", "morning_time") if k in msg]
        if not keys:
            return

        user_cache = self.active_users_cache.get(userid)
        if not user_cache:
            self.logger.warning(f"User {userid} not in cache; preference update ignored")
            return

        for k in keys:
            user_cache[k] = msg[k]
            self.logger.info(f"Updated {k} for user {userid}: {msg[k]}")


    def _get_actuators_in_room(self, room_id):
        """
        Return the list of actuator types for room_id.
        Cached after the first successful call; cleared automatically on eviction.
        """
        if room_id in self._actuator_cache:
            return self._actuator_cache[room_id]

        try:
            res = requests.get(f"{self.catalog_url}/getActuatorByRoom",
                               params={"room_id": room_id})
        except requests.RequestException as e:
            self.logger.error(f"Network error fetching actuators for room {room_id}: {e}")
            return []

        if res.status_code != 200:
            self.logger.error(
                f"Error fetching actuators for room {room_id}: {res.status_code} - {res.text}"
            )
            return []

        try:
            actuator_types = list({
                a["type"] for a in res.json().get("actuators", []) if a.get("type")
            })
            self._actuator_cache[room_id] = actuator_types
            self.logger.info(f"Actuator cache populated for room {room_id}: {actuator_types}")
            return actuator_types
        except Exception as e:
            self.logger.error(f"Error decoding actuator response for room {room_id}: {e}")
            return []


    def _handle_temperature(self, msg, room_actuators, desired_temperature, houseid, bedroomid):
        entry = msg['e'][0]
        if entry.get('t') is None:
            self.logger.warning(f"[TEMP] Missing timestamp in payload for room {bedroomid}, skipping")
            return
        temp_value  = float(entry['v'])
        sensor_ts   = int(float(entry['t']))
        desired_temperature = float(desired_temperature)
        tol                 = max(0.0, self.temperature_tolerance)
        base_topic          = self.topic_publish[0]

        def _send(device, action):
            self.publish(
                {"action": action, "timestamp": sensor_ts},
                command_topic=base_topic.format(houseID=houseid, bedroomid=bedroomid, device=device),
            )

        # In deadband: turn both HVAC devices off to avoid oscillation
        if abs(temp_value - desired_temperature) <= tol:
            for device in ("fan", "heater"):
                if device in room_actuators:
                    _send(device, 0)
            return

        prefer_fan = getattr(self.phase_manager, 'prefer_fan', True)
        action, device = _resolve_temperature_action(
            temp_value, desired_temperature, room_actuators,
            prefer_fan=prefer_fan, tolerance=tol,
        )
        if device is None:
            return

        _send(device, action)
        # Ensure mutual exclusivity
        opposite = "heater" if device == "fan" else "fan"
        if opposite in room_actuators:
            _send(opposite, 0)


    def _handle_presence(self, msg, userid, houseid, bedroomid):
        entry = msg['e'][0]
        if entry.get('t') is None:
            self.logger.warning(f"[PRESENCE] Missing timestamp in payload for room {bedroomid}, skipping")
            return
        presence_value = entry['v']
        sensor_ts      = int(float(entry['t']))

        user_data = self.active_users_cache.get(userid)
        if not user_data:
            self.logger.warning(f"User {userid} not found in cache for presence handling")
            return

        lv              = user_data["live_values"]
        finish_topic    = self.topic_publish[2].format(userid=userid, bedroomid=bedroomid)

        if presence_value != 1:
            # User is out of bed
            if lv.get("last_left_bed") is None:
                lv["last_left_bed"] = datetime.now()
            elif (
                user_data.get("is_sleeping", False)
                and (datetime.now() - lv["last_left_bed"]).total_seconds() >= self.WAKE_DETECTION_SECONDS
            ):
                user_data["is_sleeping"] = False
                lv["last_seen_bed"] = lv["last_left_bed"] = None
                self.publish({"action": "FINISH_SLEEP", "timestamp": sensor_ts}, command_topic=finish_topic)
                self.logger.info(f"User {userid} finished sleep in {bedroomid}")
            return

        # User is in bed
        lv["last_left_bed"] = None
        if lv.get("last_seen_bed") is None:
            lv["last_seen_bed"] = datetime.now()
            return

        if (
            not user_data.get("is_sleeping", False)
            and (datetime.now() - lv["last_seen_bed"]).total_seconds() >= self.SLEEP_DETECTION_SECONDS
        ):
            user_data["is_sleeping"] = True
            self.publish(
                {"action": 1, "timestamp": sensor_ts},
                command_topic=self.topic_publish[1].format(houseID=houseid, bedroomid=bedroomid),
            )
            self.logger.info(f"User {userid} is now sleeping in {bedroomid}")


    def change_target_temperature_light(self, userid, target_temperature=None,
                                         target_light=None, phase=None):
        """Update live targets and publish light/phase/sleep events via MQTT."""
        user_data = self.active_users_cache.get(userid)
        if not user_data:
            self.logger.warning(f"User {userid} not found in cache for target update")
            return

        lt = user_data["live_targets"]
        lv = user_data["live_values"]

        previous_light   = lt.get("light")
        previous_phase   = lv.get("phase")
        phase_published  = lv.get("phase_published",  False)
        start_sleep_sent = lv.get("start_sleep_sent", False)

        if target_temperature is not None:
            lt["temperature"] = target_temperature
        if target_light is not None:
            lt["light"] = target_light
        if phase is not None:
            lv["phase"] = phase

        houseid   = user_data.get("house_id")
        bedroomid = user_data.get("active_room_id")

        # Publish light only when the rounded integer value actually changes
        if target_light is not None:
            new_val = int(round(max(0.0, min(100.0, float(target_light)))))
            old_val = None if previous_light is None else int(round(previous_light))
            if old_val != new_val:
                self.publish(
                    {"action": "SET", "value": new_val},
                    command_topic=f"House/{houseid}/Bedroom/{bedroomid}/actuator/light/command",
                )
                self.logger.info(f"Light SET value={new_val} phase={phase} user={userid}")

        # Publish phase on first call, on change, or during active transitions
        is_transition = phase in ("WIND_DOWN", "WAKE_UP")
        if phase is not None and (not phase_published or phase != previous_phase or is_transition):
            self.publish(
                {"bn": f"{houseid}:{bedroomid}:phase",
                 "e": [{"n": "Phase", "v": phase, "t": int(time.time())}]},
                command_topic=self.topic_publish[4].format(houseid=houseid, bedroomid=bedroomid),
            )
            lv["phase_published"] = True
            self.logger.info(f"Published phase={phase} for user={userid}")

            ts = _sensor_ts_int(lv)
            if ts is None:
                self.logger.warning(f"[PHASE] Missing sensor_ts for user={userid}, sleep events skipped")
                return

            if phase == "SLEEP" and not start_sleep_sent:
                self.publish(
                    {"action": "START_SLEEP", "timestamp": ts},
                    command_topic=self.topic_publish[3].format(userid=userid, bedroomid=bedroomid),
                )
                lv["start_sleep_sent"] = True
                self.logger.info(f"START_SLEEP user={userid} ts={ts}")

            if previous_phase == "SLEEP" and phase != "SLEEP":
                self.publish(
                    {"action": "FINISH_SLEEP", "timestamp": ts},
                    command_topic=self.topic_publish[2].format(userid=userid, bedroomid=bedroomid),
                )
                lv["start_sleep_sent"] = False
                self.logger.info(f"FINISH_SLEEP user={userid} ts={ts}")


def _sensor_ts_int(lv: dict):
    """Extract sensor_ts from live_values as an integer epoch second. Returns None if missing."""
    raw = lv.get("sensor_ts")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None



if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    logger = logging.getLogger(__name__)

    try:
        with open("conf.json", "r") as f:
            full_conf = json.load(f)
    except FileNotFoundError:
        logger.error("Configuration file 'conf.json' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in 'conf.json': {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading configuration file: {e}")
        sys.exit(1)

    # Configure the dispatcher to use GET/POST/PUT/DELETE methods
    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}


    try:
        sleep_cycle_manager = SleepCycleManager(full_conf, logger=logger)
        cherrypy.tree.mount(sleep_cycle_manager, '/', conf)
        cherrypy.config.update({
            'server.socket_host': full_conf['serviceInfo']['host'],
            'server.socket_port': full_conf['serviceInfo']['port'],
            'error_page.default':  json_error_page,
        })

        cherrypy.engine.subscribe('start', sleep_cycle_manager.catalog_client.start_background_loop)
        cherrypy.engine.subscribe('stop', sleep_cycle_manager.catalog_client.stop_background_loop)
        cherrypy.engine.subscribe('stop', sleep_cycle_manager.catalog_client.unregister)

        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)
