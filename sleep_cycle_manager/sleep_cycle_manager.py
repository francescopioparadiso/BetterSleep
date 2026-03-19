import json
import os
import sys
import time
import logging
import threading
import cherrypy
import requests
import re
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.common import mqtt_to_regex, json_error_page, init_mqtt_helper
from phase_manager import PhaseManager
from user_cache import UserCache, UserEntry


# ---------------------------------------------------------------------------
# Pure helpers (no state)
# ---------------------------------------------------------------------------

def _resolve_temperature_action(temp_value, desired_temperature, room_actuators,
                                 prefer_fan=True, tolerance=0.0):
    temp_value          = float(temp_value)
    desired_temperature = float(desired_temperature)
    tol                 = max(0.0, float(tolerance))

    too_hot  = temp_value > desired_temperature + tol
    too_cold = temp_value < desired_temperature - tol

    if too_hot:
        if prefer_fan and "fan" in room_actuators:
            return 1, "fan"
        if "heater" in room_actuators:
            return 0, "heater"
        if "fan" in room_actuators:
            return 1, "fan"

    if too_cold:
        if "heater" in room_actuators:
            return 1, "heater"
        if "fan" in room_actuators:
            return 0, "fan"

    return None, None


def _parse_preference_topic(topic):
    parts = topic.split("/")
    if len(parts) >= 5 and parts[2] == "User":
        return "user", parts[3]
    if len(parts) >= 8 and parts[2] == "House":
        return "room", parts[5]
    return None, None


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class SleepCycleManager:
    exposed = True

    _DEFAULT_SLEEP_DETECTION_SECONDS   = 1800
    _DEFAULT_WAKE_DETECTION_SECONDS    = 300
    _DEFAULT_USER_CACHE_TTL_SECONDS    = 7200
    _DEFAULT_EVICTION_INTERVAL_SECONDS = 300

    def __init__(self, conf, logger=None):
        self.mqtt_client = None
        self.logger = logger or logging.getLogger(__name__)

        self.catalog_url  = conf['catalogURL']
        self.service_info = conf['serviceInfo']

        self.catalog_client = CatalogClient(
            self.catalog_url, self.service_info, conf.get('removeInterval', 10)
        )
        self.catalog_client.register()

        self.MQTT_info             = conf['MQTT']
        self.user_service_endpoint = self._get_endpoint_user_service()
        self.topic_subscribe_raw   = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [
            re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw
        ]
        self._topic_handlers = [
            self._handle_sensor_topic,
            self._handle_actuator_state,
            self._handle_preference_topic,
            self._handle_catalog_actuator_added,
            self._handle_catalog_actuator_removed,
        ]
        self.topic_publish = self.MQTT_info.get('topic_publish')

        self.temperature_tolerance   = float(conf.get('temperatureTolerance', 0.5))
        self.SLEEP_DETECTION_SECONDS = int(conf.get('sleepDetectionSec', self._DEFAULT_SLEEP_DETECTION_SECONDS))
        self.WAKE_DETECTION_SECONDS  = int(conf.get('wakeDetectionSec',  self._DEFAULT_WAKE_DETECTION_SECONDS))

        self._lock = threading.RLock()

        # Shared room→user map (UserCache writes into this, manager reads it)
        self.room_to_user_map: dict[str, str] = {}

        # Presence state kept separate — datetime objects, not cache data
        # { userid: {"last_seen_bed": datetime|None, "last_left_bed": datetime|None} }
        self._presence_state: dict[str, dict] = {}

        self.user_cache = UserCache(
            user_service_endpoint = self.user_service_endpoint,
            catalog_url           = self.catalog_url,
            room_to_user_map      = self.room_to_user_map,
            ttl_seconds           = int(conf.get('userCacheTTLSec',     self._DEFAULT_USER_CACHE_TTL_SECONDS)),
            eviction_interval     = int(conf.get('evictionIntervalSec', self._DEFAULT_EVICTION_INTERVAL_SECONDS)),
            logger                = self.logger,
        )

        self.phase_manager = PhaseManager(
            manager_instance          = self,
            transition_window_min     = conf.get('transitionWindowMin', 30),
            transition_curve_exponent = conf.get('transitionCurveExponent', 1.0),
            prefer_fan                = conf.get('preferFan', True),
        )

        self._init_mqtt_client()
        self.user_cache.seed_room_associations()
        self.user_cache.start_eviction_loop()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _get_endpoint_user_service(self):
        data, status, error = self.catalog_client.get("getEndpointUserService")
        endpoint = (data or {}).get("endpoint") if status == 200 else None
        if endpoint:
            self.logger.info(f"User service endpoint retrieved: {endpoint}")
            return endpoint
        self.logger.error(f"Error retrieving user service endpoint: {status} - {error}")
        return None

    def _init_mqtt_client(self):
        try:
            self.mqtt_client = init_mqtt_helper(self, self.MQTT_info, self.logger)
            if self.mqtt_client is None:
                self.catalog_client.unregister()
                sys.exit(1)
            self.logger.info(f"MQTT client initialised and subscribed to {self.topic_subscribe_raw}")
        except Exception as e:
            self.logger.error(f"Error initialising MQTT client: {e}")
            self.catalog_client.unregister()
            sys.exit(1)

    # ------------------------------------------------------------------
    # MQTT lifecycle
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # MQTT routing
    # ------------------------------------------------------------------

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
        except json.JSONDecodeError:
            self.logger.error(f"Invalid JSON payload received on topic {topic}")
            return

        for index, regex in enumerate(self.topic_subscribe_regex):
            if not regex.match(topic):
                continue

            handler = self._topic_handlers[index] if index < len(self._topic_handlers) else None
            if handler:
                handler(topic, message_received)
            else:
                self.logger.warning(f"No handler mapped for topic index {index}: {topic}")
            return

        self.logger.warning(f"Message on unrecognised topic: {topic}")

    def _handle_actuator_state(self, topic, msg):
        # Currently unused; placeholder for actuator telemetry if needed
        return

    # ------------------------------------------------------------------
    # Sensor topic
    # ------------------------------------------------------------------

    def _handle_sensor_topic(self, topic, msg):
        parts = topic.split("/")
        if len(parts) < 8:
            self.logger.warning(f"Invalid sensor topic format: {topic}")
            return

        house_id    = parts[1]
        room_id     = parts[3]
        sensor_type = parts[5]

        with self._lock:
            userid = self.room_to_user_map.get(room_id)
            if userid is None:
                self.logger.warning(
                    f"[SENSOR SKIPPED] room_id={room_id!r} not in room_to_user_map "
                    f"(keys: {list(self.room_to_user_map.keys())})"
                )
                return

            entry = self.user_cache.get_or_fetch(userid)
            if not entry:
                return

            self.user_cache.touch(userid)

            ts = msg['e'][0].get('t') if msg.get('e') else None
            if ts is not None:
                entry.sensor_ts = int(float(ts))
            else:
                self.logger.warning(f"[PHASE SYNC SKIPPED] no timestamp in payload for user={userid}")

            phase     = entry.phase
            live_tgt  = entry.live_targets
            config    = entry.config
            actuators = self.user_cache.get_actuators_for_room(room_id)

        if ts is not None:
            try:
                self.logger.info(
                    f"-> {datetime.fromtimestamp(float(ts)).strftime('%H:%M')}"
                )
                self.phase_manager.sync_from_sensor_time(float(ts), userid)
            except Exception as e:
                self.logger.error(f"[PHASE SYNC ERROR] {e}")

        if sensor_type == "ambient_temp":
            desired_temp = live_tgt.get('temperature') or (
                config['temperature_night'] if phase == "SLEEP"
                else config['temperature_morning']
            )
            self.logger.info(
                f"[TEMP] room={room_id} phase={phase} desired={desired_temp} actuators={actuators}"
            )
            self._handle_temperature(msg, actuators, desired_temp, house_id, room_id)

        elif sensor_type == "presence":
            self._handle_presence(msg, userid, house_id, room_id)

        elif sensor_type == "light":
            with self._lock:
                entry = self.user_cache.get(userid)
                if entry:
                    try:
                        entry.light = float(msg['e'][0]['v'])
                    except Exception:
                        self.logger.warning(f"Invalid light payload for user {userid}: {msg}")

    # ------------------------------------------------------------------
    # Preference topic
    # ------------------------------------------------------------------

    def _handle_preference_topic(self, topic, msg):
        preference_kind, entity_id = _parse_preference_topic(topic)
        if preference_kind == "user":
            self._update_user_preferences(entity_id, msg)
        else:
            self.logger.warning(f"Unhandled preference topic: {topic}")

    def _update_user_preferences(self, userid, msg):
        keys = {k: msg[k] for k in ("night_time", "morning_time") if k in msg}
        if not keys:
            return
        if not self.user_cache.patch_preferences(userid, keys):
            self.logger.warning(f"User {userid} not in cache; preference update ignored")

    # ------------------------------------------------------------------
    # Catalog actuator events
    # ------------------------------------------------------------------

    def _handle_catalog_actuator_added(self, topic, msg):
        parts = topic.split("/")
        if len(parts) < 6:
            self.logger.warning(f"Invalid actuator-added topic: {topic}")
            return

        room_id       = parts[5]
        actuator_type = msg.get("type")
        if actuator_type:
            actuator_type = str(actuator_type).lower()

        with self._lock:
            if actuator_type:
                self.user_cache.add_actuator(room_id, actuator_type)
            else:
                self.user_cache.invalidate_actuators(room_id)

    def _handle_catalog_actuator_removed(self, topic, msg):
        parts = topic.split("/")
        if len(parts) < 6:
            self.logger.warning(f"Invalid actuator-removed topic: {topic}")
            return

        room_id       = parts[5]
        actuator_type = msg.get("type")
        if actuator_type:
            actuator_type = str(actuator_type).lower()

        with self._lock:
            if actuator_type:
                self.user_cache.remove_actuator(room_id, actuator_type)
            else:
                self.user_cache.invalidate_actuators(room_id)


    # ------------------------------------------------------------------
    # Temperature control
    # ------------------------------------------------------------------

    def _handle_temperature(self, msg, room_actuators, desired_temperature, houseid, bedroomid):
        entry = msg['e'][0]
        if entry.get('t') is None:
            self.logger.warning(f"[TEMP] Missing timestamp in payload for room {bedroomid}, skipping")
            return

        temp_value = float(entry['v'])
        sensor_ts  = int(float(entry['t']))
        tol        = max(0.0, self.temperature_tolerance)
        base_topic = self.topic_publish[0]

        def _send(device, action):
            self.publish(
                {"action": action, "timestamp": sensor_ts},
                command_topic=base_topic.format(houseID=houseid, bedroomid=bedroomid, device=device),
            )

        if abs(temp_value - float(desired_temperature)) <= tol:
            for device in ("fan", "heater"):
                if device in room_actuators:
                    _send(device, 0)
            return

        action, device = _resolve_temperature_action(
            temp_value, desired_temperature, room_actuators,
            prefer_fan=self.phase_manager.prefer_fan,
            tolerance=tol,
        )
        if device is None:
            return

        _send(device, action)
        opposite = "heater" if device == "fan" else "fan"
        if opposite in room_actuators:
            _send(opposite, 0)

    # ------------------------------------------------------------------
    # Presence / sleep detection
    # ------------------------------------------------------------------

    def _handle_presence(self, msg, userid, houseid, bedroomid):
        msg_entry = msg['e'][0]
        if msg_entry.get('t') is None:
            self.logger.warning(f"[PRESENCE] Missing timestamp in payload for room {bedroomid}, skipping")
            return

        presence_value = msg_entry['v']
        sensor_ts      = int(float(msg_entry['t']))
        finish_topic   = self.topic_publish[2].format(userid=userid, bedroomid=bedroomid)

        publish_finish_sleep = False
        publish_start_sleep  = False

        with self._lock:
            entry = self.user_cache.get(userid)
            if not entry:
                self.logger.warning(f"User {userid} not found in cache for presence handling")
                return

            ps = self._presence_state.setdefault(
                userid, {"last_seen_bed": None, "last_left_bed": None}
            )

            if presence_value != 1:
                if ps["last_left_bed"] is None:
                    ps["last_left_bed"] = datetime.now()
                elif (
                    entry.is_sleeping
                    and (datetime.now() - ps["last_left_bed"]).total_seconds() >= self.WAKE_DETECTION_SECONDS
                ):
                    entry.is_sleeping      = False
                    ps["last_seen_bed"]    = None
                    ps["last_left_bed"]    = None
                    publish_finish_sleep   = True
            else:
                ps["last_left_bed"] = None
                if ps["last_seen_bed"] is None:
                    ps["last_seen_bed"] = datetime.now()
                elif (
                    not entry.is_sleeping
                    and (datetime.now() - ps["last_seen_bed"]).total_seconds() >= self.SLEEP_DETECTION_SECONDS
                ):
                    entry.is_sleeping   = True
                    publish_start_sleep = True

        if publish_finish_sleep:
            self.publish({"action": "FINISH_SLEEP", "timestamp": sensor_ts}, command_topic=finish_topic)
            self.logger.info(f"User {userid} finished sleep in {bedroomid}")

        if publish_start_sleep:
            self.publish(
                {"action": 1, "timestamp": sensor_ts},
                command_topic=self.topic_publish[1].format(houseID=houseid, bedroomid=bedroomid),
            )
            self.logger.info(f"User {userid} is now sleeping in {bedroomid}")

    # ------------------------------------------------------------------
    # Phase / target update (called by PhaseManager)
    # ------------------------------------------------------------------

    def change_target_temperature_light(self, userid, target_temperature=None,
                                         target_light=None, phase=None):
        with self._lock:
            entry = self.user_cache.get(userid)
            if not entry:
                self.logger.warning(f"User {userid} not found in cache for target update")
                return

            previous_light   = entry.live_targets.get("light")
            previous_phase   = entry.phase
            phase_published  = entry.phase_published
            start_sleep_sent = entry.start_sleep_sent

            if target_temperature is not None:
                entry.live_targets["temperature"] = target_temperature
            if target_light is not None:
                entry.live_targets["light"] = target_light
            if phase is not None:
                entry.phase = phase

            houseid   = entry.house_id
            bedroomid = entry.active_room_id
            sensor_ts = entry.sensor_ts

            publishes = []

            if target_light is not None:
                new_val = int(round(max(0.0, min(100.0, float(target_light)))))
                old_val = None if previous_light is None else int(round(previous_light))
                if old_val != new_val:
                    publishes.append((
                        {"action": "SET", "value": new_val},
                        f"House/{houseid}/Bedroom/{bedroomid}/actuator/light/command",
                        f"Light SET value={new_val} phase={phase} user={userid}",
                    ))

            is_transition = phase in ("WIND_DOWN", "WAKE_UP")
            if phase is not None and (not phase_published or phase != previous_phase or is_transition):
                publishes.append((
                    {"bn": f"{houseid}:{bedroomid}:phase",
                     "e": [{"n": "Phase", "v": phase, "t": int(time.time())}]},
                    self.topic_publish[4].format(houseid=houseid, bedroomid=bedroomid),
                    f"Published phase={phase} for user={userid}",
                ))
                entry.phase_published = True

                if sensor_ts is None:
                    self.logger.warning(f"[PHASE] Missing sensor_ts for user={userid}, sleep events skipped")
                else:
                    if phase == "SLEEP" and not start_sleep_sent:
                        publishes.append((
                            {"action": "START_SLEEP", "timestamp": sensor_ts},
                            self.topic_publish[3].format(userid=userid, bedroomid=bedroomid),
                            f"START_SLEEP user={userid} ts={sensor_ts}",
                        ))
                        entry.start_sleep_sent = True

                    if previous_phase == "SLEEP" and phase != "SLEEP":
                        publishes.append((
                            {"action": "FINISH_SLEEP", "timestamp": sensor_ts},
                            self.topic_publish[2].format(userid=userid, bedroomid=bedroomid),
                            f"FINISH_SLEEP user={userid} ts={sensor_ts}",
                        ))
                        entry.start_sleep_sent = False

        for message, topic, log_msg in publishes:
            self.publish(message, command_topic=topic)
            self.logger.info(log_msg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
        cherrypy.engine.subscribe('stop',  sleep_cycle_manager.catalog_client.stop_background_loop)
        cherrypy.engine.subscribe('stop',  sleep_cycle_manager.catalog_client.unregister)

        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)

