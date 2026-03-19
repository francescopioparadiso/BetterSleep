import json
import os
import sys
import time
import logging
import threading
import re
from datetime import datetime

import cherrypy

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.common import mqtt_to_regex, json_error_page, init_mqtt_helper
from phase_manager import PhaseManager
from user_cache import UserCache


def _resolve_temperature_action(temp, desired, actuators, prefer_fan=True, tol=0.0):
    too_hot  = float(temp) > float(desired) + tol
    too_cold = float(temp) < float(desired) - tol

    if too_hot:
        if prefer_fan and "fan" in actuators:   return 1, "fan"
        if "heater"   in actuators:             return 0, "heater"
        if "fan"      in actuators:             return 1, "fan"

    if too_cold:
        if "heater" in actuators:               return 1, "heater"
        if "fan"    in actuators:               return 0, "fan"

    return None, None


def _parse_preference_topic(topic):
    parts = topic.split("/")
    if len(parts) >= 5 and parts[2] == "User":  return "user", parts[3]
    if len(parts) >= 8 and parts[2] == "House": return "room", parts[5]
    return None, None


class SleepCycleManager:
    exposed = True

    SLEEP_DETECT_SEC   = 1800
    WAKE_DETECT_SEC    = 300
    USER_CACHE_TTL_SEC = 7200
    EVICTION_SEC       = 300

    def __init__(self, conf, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self._lock  = threading.RLock()

        self.catalog_client = CatalogClient(
            conf['catalogURL'], conf['serviceInfo'], conf.get('removeInterval', 10)
        )
        self.catalog_client.register()

        mqtt = conf['MQTT']
        self.topic_subscribe_raw   = mqtt['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]
        self.topic_publish         = mqtt.get('topic_publish')
        self.temperature_tolerance = float(conf.get('temperatureTolerance', 0.5))
        self.SLEEP_DETECT_SEC      = int(conf.get('sleepDetectionSec', self.SLEEP_DETECT_SEC))
        self.WAKE_DETECT_SEC       = int(conf.get('wakeDetectionSec',  self.WAKE_DETECT_SEC))

        self.room_to_user_map: dict[str, str] = {}
        self._presence_state:  dict[str, dict] = {}

        user_svc = self._get_user_service_endpoint()
        self.user_cache = UserCache(
            user_service_endpoint=user_svc,
            catalog_url=conf['catalogURL'],
            room_to_user_map=self.room_to_user_map,
            ttl_seconds=int(conf.get('userCacheTTLSec',      self.USER_CACHE_TTL_SEC)),
            eviction_interval=int(conf.get('evictionIntervalSec', self.EVICTION_SEC)),
            logger=self.logger,
        )
        self.phase_manager = PhaseManager(
            manager_instance=self,
            transition_window_min=conf.get('transitionWindowMin', 30),
            transition_curve_exponent=conf.get('transitionCurveExponent', 1.0),
            prefer_fan=conf.get('preferFan', True),
        )

        self._topic_handlers = [
            self._handle_sensor_topic,
            self._handle_actuator_state,
            self._handle_preference_topic,
            self._handle_catalog_actuator_added,
            self._handle_catalog_actuator_removed,
        ]

        self.mqtt_client = init_mqtt_helper(self, mqtt, self.logger)
        if self.mqtt_client is None:
            self.catalog_client.unregister()
            sys.exit(1)

        self.user_cache.seed_room_associations()
        self.user_cache.start_eviction_loop()

    def _get_user_service_endpoint(self):
        data, status, error = self.catalog_client.get("getEndpointUserService")
        endpoint = (data or {}).get("endpoint") if status == 200 else None
        if not endpoint:
            self.logger.error(f"Could not fetch user-service endpoint: {status} - {error}")
            self.stopClient()
            self.catalog_client.unregister()
            sys.exit(1)
        return endpoint

    def startClient(self): self.mqtt_client.start()
    def stopClient(self):  self.mqtt_client.stop()

    def publish(self, message, command_topic=None):
        try:
            self.mqtt_client.myPublish(command_topic, message)
            self.logger.info(f"Published -> {command_topic}: {message}")
        except Exception as e:
            self.logger.error(f"Publish error: {e}")

    def notify(self, topic, payload):
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            self.logger.error(f"Bad JSON on {topic}")
            return

        for idx, rx in enumerate(self.topic_subscribe_regex):
            if not rx.match(topic):
                continue
            handler = self._topic_handlers[idx] if idx < len(self._topic_handlers) else None
            if handler:
                handler(topic, msg)
            else:
                self.logger.warning(f"No handler for topic index {idx}: {topic}")
            return

        self.logger.warning(f"Unrecognised topic: {topic}")

    def _handle_actuator_state(self, topic, msg):
        pass

    def _handle_sensor_topic(self, topic, msg):
        parts = topic.split("/")
        if len(parts) < 8:
            self.logger.warning(f"Short sensor topic: {topic}")
            return

        house_id, room_id, sensor_type = parts[1], parts[3], parts[5]

        with self._lock:
            userid = self.room_to_user_map.get(room_id)
            if not userid:
                self.logger.warning(f"Room {room_id!r} not in room_to_user_map")
                return

            entry = self.user_cache.get_or_fetch(userid)
            if not entry:
                return

            self.user_cache.touch(userid)
            ts = msg['e'][0].get('t') if msg.get('e') else None
            if ts is not None:
                entry.sensor_ts = int(float(ts))

            phase, live_tgt, config = entry.phase, entry.live_targets, entry.config
            actuators = self.user_cache.get_actuators_for_room(room_id)

        if ts is not None:
            try:
                self.phase_manager.sync_from_sensor_time(float(ts), userid)
            except Exception as e:
                self.logger.error(f"Phase sync error: {e}")

        if sensor_type == "ambient_temp":
            desired = live_tgt.get('temperature') or (
                config['temperature_night'] if phase == "SLEEP" else config['temperature_morning']
            )
            self._handle_temperature(msg, actuators, desired, house_id, room_id)

        elif sensor_type == "presence":
            self._handle_presence(msg, userid, house_id, room_id)

        elif sensor_type == "light":
            with self._lock:
                entry = self.user_cache.get(userid)
                if entry:
                    try:
                        entry.actuators_state["light"] = float(msg['e'][0]['v'])
                    except Exception:
                        self.logger.warning(f"Bad light payload for {userid}: {msg}")

    def _handle_preference_topic(self, topic, msg):
        kind, entity_id = _parse_preference_topic(topic)
        if kind == "user":
            keys = {k: msg[k] for k in ("night_time", "morning_time") if k in msg}
            if keys and not self.user_cache.patch_preferences(entity_id, keys):
                self.logger.warning(f"User {entity_id} not in cache; preference skipped")
        else:
            self.logger.warning(f"Unhandled preference topic: {topic}")

    def _handle_catalog_actuator_added(self, topic, msg):
        self._update_catalog_actuator(topic, msg, add=True)

    def _handle_catalog_actuator_removed(self, topic, msg):
        self._update_catalog_actuator(topic, msg, add=False)

    def _update_catalog_actuator(self, topic, msg, add: bool):
        parts = topic.split("/")
        if len(parts) < 6:
            self.logger.warning(f"Short actuator topic: {topic}")
            return
        room_id = parts[5]
        atype   = str(msg["type"]).lower() if msg.get("type") else None
        with self._lock:
            if atype:
                (self.user_cache.add_actuator if add else self.user_cache.remove_actuator)(room_id, atype)
            else:
                self.user_cache.invalidate_actuators(room_id)

    def _handle_temperature(self, msg, actuators, desired, house_id, room_id):
        e = msg['e'][0]
        if e.get('t') is None:
            self.logger.warning(f"Missing timestamp for room {room_id}")
            return

        temp, ts = float(e['v']), int(float(e['t']))
        tol      = max(0.0, self.temperature_tolerance)
        base     = self.topic_publish[0]

        # Track last known actuator states per room
        with self._lock:
            userid = self.room_to_user_map.get(room_id)
            entry = self.user_cache.get(userid) if userid else None
            if entry is None:
                self.logger.warning(f"No UserEntry found for room {room_id}")
                return
            last_states = entry.actuators_state

            def send_if_changed(device, action):
                prev = last_states.get(device)
                if prev != action:
                    self.publish(
                        {"action": action, "timestamp": ts},
                        command_topic=base.format(houseID=house_id, bedroomid=room_id, device=device),
                    )
                    last_states[device] = action
                    self.logger.info(f"Sent to {device} in {room_id}: {action}")
                else:
                    self.logger.debug(f"No change for {device} in {room_id}: remains {action}")

            if abs(temp - float(desired)) <= tol:
                for dev in ("fan", "heater"):
                    if dev in actuators:
                        send_if_changed(dev, 0)
                return

            action, device = _resolve_temperature_action(
                temp, desired, actuators, self.phase_manager.prefer_fan, tol
            )
            if device:
                send_if_changed(device, action)
                opposite = "heater" if device == "fan" else "fan"
                if opposite in actuators:
                    send_if_changed(opposite, 0)

    def _handle_presence(self, msg, userid, house_id, room_id):
        e = msg['e'][0]
        if e.get('t') is None:
            self.logger.warning(f"Missing timestamp for presence in {room_id}")
            return

        present, ts  = e['v'], int(float(e['t']))
        finish_topic = self.topic_publish[2].format(userid=userid, bedroomid=room_id)
        do_start = do_finish = False

        with self._lock:
            entry = self.user_cache.get(userid)
            if not entry:
                return

            ps  = self._presence_state.setdefault(userid, {"last_seen_bed": None, "last_left_bed": None})
            now = datetime.now()

            if present != 1:
                if ps["last_left_bed"] is None:
                    ps["last_left_bed"] = now
                elif entry.is_sleeping and (now - ps["last_left_bed"]).total_seconds() >= self.WAKE_DETECT_SEC:
                    entry.is_sleeping, ps["last_seen_bed"], ps["last_left_bed"] = False, None, None
                    do_finish = True
            else:
                ps["last_left_bed"] = None
                if ps["last_seen_bed"] is None:
                    ps["last_seen_bed"] = now
                elif not entry.is_sleeping and (now - ps["last_seen_bed"]).total_seconds() >= self.SLEEP_DETECT_SEC:
                    entry.is_sleeping = True
                    do_start = True

        if do_finish:
            self.publish({"action": "FINISH_SLEEP", "timestamp": ts}, command_topic=finish_topic)
            self.logger.info(f"User {userid} woke up in {room_id}")

        if do_start:
            self.publish(
                {"action": 1, "timestamp": ts},
                command_topic=self.topic_publish[1].format(houseID=house_id, bedroomid=room_id),
            )
            self.logger.info(f"User {userid} fell asleep in {room_id}")

    def change_target_temperature_light(self, userid, target_temperature=None,
                                        target_light=None, phase=None):
        with self._lock:
            entry = self.user_cache.get(userid)
            if not entry:
                self.logger.warning(f"User {userid} not in cache")
                return

            prev_phase = entry.phase

            if target_temperature is not None:
                entry.live_targets["temperature"] = target_temperature
            if target_light is not None:
                entry.live_targets["light"] = target_light
            if phase is not None:
                entry.phase = phase

            house_id, room_id, ts = entry.house_id, entry.active_room_id, entry.sensor_ts
            publishes = []

            # Use actuators_state to track last sent value for light
            if target_light is not None:
                new_val = int(round(max(0.0, min(100.0, float(target_light)))))
                prev_sent_light = entry.actuators_state.get("light")
                if prev_sent_light != new_val:
                    publishes.append((
                        {"action": "SET", "value": new_val},
                        f"House/{house_id}/Bedroom/{room_id}/actuator/light/command",
                    ))
                    entry.actuators_state["light"] = new_val

            is_transition = phase in ("WIND_DOWN", "WAKE_UP")
            if phase and (not entry.phase_published or phase != prev_phase or is_transition):
                publishes.append((
                    {"bn": f"{house_id}:{room_id}:phase",
                     "e": [{"n": "Phase", "v": phase, "t": int(time.time())}]},
                    self.topic_publish[4].format(houseid=house_id, bedroomid=room_id),
                ))
                entry.phase_published = True

                if ts is None:
                    self.logger.warning(f"Missing sensor_ts for user={userid}; sleep events skipped")
                else:
                    if phase == "SLEEP" and not entry.start_sleep_sent:
                        publishes.append((
                            {"action": "START_SLEEP", "timestamp": ts},
                            self.topic_publish[3].format(userid=userid, bedroomid=room_id),
                        ))
                        entry.start_sleep_sent = True

                    if prev_phase == "SLEEP" and phase != "SLEEP":
                        publishes.append((
                            {"action": "FINISH_SLEEP", "timestamp": ts},
                            self.topic_publish[2].format(userid=userid, bedroomid=room_id),
                        ))
                        entry.start_sleep_sent = False

        for message, topic in publishes:
            self.publish(message, command_topic=topic)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )
    logger = logging.getLogger(__name__)

    try:
        with open("conf.json") as f:
            full_conf = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, Exception) as e:
        logger.error(f"Config error: {e}")
        sys.exit(1)

    manager = SleepCycleManager(full_conf, logger=logger)

    cherrypy.tree.mount(manager, '/', {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}})
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port'],
        'error_page.default': json_error_page,
    })
    cherrypy.engine.subscribe('start', manager.catalog_client.start_background_loop)
    cherrypy.engine.subscribe('stop',  manager.catalog_client.stop_background_loop)
    cherrypy.engine.subscribe('stop',  manager.catalog_client.unregister)

    cherrypy.engine.start()
    cherrypy.engine.block()