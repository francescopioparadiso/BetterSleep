import json
import os
import sys
import time
import logging
import cherrypy
import requests
import re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from datetime import datetime

from common.common import mqtt_to_regex, json_error_page
from PhaseManager import PhaseManager
# Configure logging


def _resolve_temperature_action(temp_value, desired_temperature, room_actuators, prefer_fan=True, tolerance=0.0):
    temp_value = float(temp_value)
    desired_temperature = float(desired_temperature)
    tol = max(0.0, float(tolerance))

    upper_bound = desired_temperature + tol
    lower_bound = desired_temperature - tol

    # Above band -> cool down
    if temp_value > upper_bound:
        # Priority: turn ON fan to cool down
        if "fan" in room_actuators:
            return 1, "fan"
        # Fallback: turn OFF heater if no fan available
        if "heater" in room_actuators:
            return 0, "heater"
        return None, None

    # Below band -> warm up
    if temp_value < lower_bound:
        # Priority: turn ON heater to warm up
        if "heater" in room_actuators:
            return 1, "heater"
        # Fallback: turn OFF fan if no heater available
        if "fan" in room_actuators:
            return 0, "fan"
        return None, None

    # Inside deadband -> turn off all HVAC to avoid oscillation
    for device in ("fan", "heater"):
        if device in room_actuators:
            return 0, device
    return None, None


def _build_command(action, device):
    return {"action": action, "device": device, "timestamp": datetime.now().timestamp()}


def _parse_sensor_topic(topic):
    parts = topic.split("/")
    if len(parts) < 7:
        return None
    return parts[1], parts[3], parts[5]


def _parse_preference_topic(topic):
    parts = topic.split("/")

    # UserService/ChangePreference/User/{userid}/Preference/
    if len(parts) >= 5 and parts[2] == "User":
        return "user", parts[3]

    # UserService/ChangePreference/House/{houseID}/Bedroom/{bedroomID}/User/{userid}/Preference/
    if len(parts) >= 8 and parts[2] == "House":
        return "room", parts[5]

    return None, None


class SleepCycleManager:
    exposed = True
    SLEEP_DETECTION_SECONDS = 1800  # 30 minutes

    def __init__(self, conf, logger=None):
        self.mqtt_client = None
        self.logger = logger
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog_client = CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        self.catalog_client.register()
        self.MQTT_info = conf['MQTT']
        self.user_service_endpoint = self.get_endpoint_user_service()
        self.topic_subscribe_raw = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]
        transition_window_min = conf.get('transitionWindowMin', 30)
        phase_check_interval = conf.get('phaseCheckIntervalSec', 60)
        transition_curve_exponent = conf.get('transitionCurveExponent', 1.0)
        self.temperature_tolerance = float(conf.get('temperatureTolerance', 0.5))
        self.active_users_cache = {}
        self.room_to_user_map = {}
        self.topic_publish = self.MQTT_info.get('topic_publish')
        self.phase_manager = PhaseManager(
            manager_instance=self,
            transition_window_min=transition_window_min,
            check_interval=phase_check_interval,
            transition_curve_exponent=transition_curve_exponent
        )
        self.init_mqtt_client()
        self.get_ActiveRoomwithUser()

    def get_endpoint_user_service(self):
        data, status, error = self.catalog_client.get(f"getEndpointUserService")
        if status == 200 and data:
            endpoint = data.get("endpoint")
            if endpoint:
                self.logger.info(f"User service endpoint retrieved: {endpoint}")
                return endpoint
            else:
                self.logger.error("User service endpoint not found in Catalog response")
                return None
        else:
            self.logger.error(f"Error retrieving user service endpoint: {status} - {error}")
            return None

    def get_ActiveRoomwithUser(self):
        """
        Fetches active associations and normalizes them to RoomID -> Userid mapping.
        User service returns {user_id: room_id}, we need {room_id: user_id}.
        """
        try:
            res = requests.get(f"{self.user_service_endpoint}/getActiveRoomsWithUser")
            if res.status_code != 200:
                self.logger.error(f"Failed to sync associations: {res.status_code}")
                return

            data = res.json()
            # Get the active_rooms dict which has {user_id: room_id} structure
            active_rooms_map = data.get("active_rooms", {})

            # Normalize to {room_id: user_id} for our internal use
            normalized_map = {}
            for user_id, room_id in active_rooms_map.items():
                # Keep as strings - no conversion needed
                normalized_map[str(room_id)] = user_id

            self.room_to_user_map = normalized_map
            self.logger.info(f"Association map synchronized: {self.room_to_user_map}")
        except Exception as e:
            self.logger.error(f"Exception during association sync: {e}")

    def _fetch_and_cache_room_preference(self, userid):
        res = requests.get(f"{self.user_service_endpoint}/getUserRoomPreferences", params={"user_id": userid})
        if res.status_code != 200:
            return None

        data = res.json()
        pref = data.get("preferences", {})

        # Backward compatibility with nested response shape from user_service/postgres_db.
        if "user_preferences" in pref:
            pref = pref.get("user_preferences", {})

        u_id = userid  # Keep as string
        r_id = pref.get("room_id")  # Keep as string

        # 1. Cleanup: If the user changed rooms, remove them from the old room mapping
        if u_id in self.active_users_cache:
            old_r = self.active_users_cache[u_id].get('active_room_id')
            if old_r and old_r in self.room_to_user_map:
                # Only delete if this user is the one currently mapped to that room
                if self.room_to_user_map[old_r] == u_id:
                    del self.room_to_user_map[old_r]

        # 3. Update Unified Cache

        previous_cache = self.active_users_cache.get(u_id, {})
        previous_live_targets = previous_cache.get("live_targets", {})
        previous_live_values = previous_cache.get("live_values", {})

        self.active_users_cache[u_id] = {
            "active_room_id": r_id,
            "house_id": pref.get('house_id'),  # Keep as string
            "night_time": pref.get('night_time'),
            "morning_time": pref.get('morning_time'),
            "is_sleeping": pref.get('is_sleeping', previous_cache.get('is_sleeping', False)),
            "config": {
                "temperature_night": float(pref.get('temperature_night', 18.0)),
                "temperature_morning": float(pref.get('temperature_morning', 22.0)),
                "light_night": float(pref.get('light_night', 0.0)),
                "light_morning": float(pref.get('light_morning', 100.0))
            },
            "live_targets": {
                "temperature": previous_live_targets.get("temperature"),  # Target temperature
                "light": previous_live_targets.get("light")  # Target light brightness
            },
            "live_values": {
                "light": previous_live_values.get("light"),
                "light_actuator": previous_live_values.get("light_actuator"),
                "heater_state": previous_live_values.get("heater_state"),
                "fan_state": previous_live_values.get("fan_state"),
                "phase": "DAY" if not pref.get('is_sleeping', False) else "SLEEP",
                "phase_published": False,  # reset so first tick always publishes
                "start_sleep_sent": False, # tracks whether START_SLEEP was sent this night
                "last_seen_bed": previous_live_values.get("last_seen_bed"),
                "last_left_bed": previous_live_values.get("last_left_bed")
            }
        }

        # 4. Map the room to the user
        self.room_to_user_map[r_id] = u_id

        return self.active_users_cache[u_id]

    def init_mqtt_client(self):
        client_id = self.MQTT_info['clientID']
        broker = self.MQTT_info['broker']
        port = self.MQTT_info['port']
        try:
            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.startClient()
            for topic in self.topic_subscribe_raw:
                self.mqtt_client.mySubscribe(topic)
            self.logger.info(f"MQTT client initialized and subscribed to {self.topic_subscribe_raw}")
        except Exception as e:
            self.logger.error(f"Error initializing MQTT client: {e}")
            self.catalog_client.unregister()
            sys.exit(1)

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def publish(self, message, command_topic=None):
        try:
            self.mqtt_client.myPublish(command_topic, message)
            self.logger.info(f"Published message to {command_topic}: {message}")
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

        self.logger.warning(f"Received message on unrecognized topic: {topic}")

    def _handle_sensor_topic(self, topic, msg):
        # House/{houseid}/Bedroom/{roomid}/sensor/{sensor_type}/{sensorid}/data
        parts = topic.split("/")
        if len(parts) < 8:
            self.logger.warning(f"Invalid sensor topic format: {topic}")
            return

        house_id = parts[1]
        room_id = parts[3]
        sensor_type = parts[5]

        userid = self.room_to_user_map.get(room_id)

        self.logger.info(
            f"[SENSOR] topic={topic} | room_id={room_id!r} | "
            f"room_to_user_map={self.room_to_user_map} | resolved userid={userid!r}"
        )

        if userid is None:
            self.logger.warning(
                f"[PHASE SYNC SKIPPED] room_id={room_id!r} not in room_to_user_map — "
                f"map keys: {list(self.room_to_user_map.keys())}"
            )
            return

        user_data = self.active_users_cache.get(userid)
        if not user_data:
            user_data = self._fetch_and_cache_room_preference(userid)
        if not user_data:
            return

        self.logger.info(f"Handling sensor event for user {userid} in room {room_id} (house {house_id}), type: {sensor_type}")

        # Store sensor_ts BEFORE calling sync_from_sensor_time.
        # sync_from_sensor_time → _check_user → change_target_temperature_light reads sensor_ts
        # synchronously, so it must already be up-to-date when START_SLEEP is published.
        ts = msg['e'][0].get('t') if 'e' in msg and len(msg['e']) > 0 else None
        if ts is not None:
            user_data['live_values']['sensor_ts'] = ts

        # Sync PhaseManager clock for THIS user only, using this sensor's timestamp.
        try:
            if ts is not None:
                vt = datetime.fromtimestamp(float(ts))
                self.logger.info(
                    f"[PHASE SYNC] user={userid} sensor_ts={ts} → virtual_time={vt.strftime('%H:%M')}"
                )
                self.phase_manager.sync_from_sensor_time(float(ts), userid)
            else:
                self.logger.warning(f"[PHASE SYNC SKIPPED] no timestamp in payload for user={userid}")
        except Exception as e:
            self.logger.error(f"[PHASE SYNC ERROR] {e}")

        if sensor_type == "ambient_temp":
            desiderate_temp = user_data['live_targets']['temperature']
            if desiderate_temp is None:
                phase = user_data['live_values'].get('phase')
                if phase == "SLEEP":
                    desiderate_temp = user_data['config'].get('temperature_night', 18.0)
                else:
                    desiderate_temp = user_data['config'].get('temperature_morning', 22.0)
            # Fetch actuators on-demand instead of caching
            room_actuators = self.get_actuators_in_room(room_id)
            self.handle_temperature(msg, room_actuators, desiderate_temp, house_id, room_id)
        elif sensor_type == "presence":
            self.handle_presence(msg, userid, house_id, room_id)
        elif sensor_type == "light":
            try:
                current_light = float(msg['e'][0]['v'])
                # Store actual sensor reading in live_values
                user_data['live_values']['light'] = current_light
            except Exception:
                self.logger.warning(f"Invalid light payload for user {userid}: {msg}")

    def _handle_actuator_topic(self, topic, msg):
        # House/{houseid}/Bedroom/{roomid}/actuator/{device_type}/data
        parts = topic.split("/")
        if len(parts) < 7:
            self.logger.warning(f"Invalid actuator topic format: {topic}")
            return

        house_id = parts[1]
        room_id = parts[3]
        device_type = parts[5]  # light, heater, fan

        userid = self.room_to_user_map.get(room_id)
        if userid is None:
            return  # ignore events for rooms without an active user

        user_data = self.active_users_cache.get(userid)
        if not user_data:
            user_data = self._fetch_and_cache_room_preference(userid)
        if not user_data:
            return

        self.logger.info(f"Handling actuator event for user {userid} in room {room_id}, device: {device_type}")

        try:
            # Extract value from SenML payload
            if 'e' in msg and len(msg['e']) > 0:
                value = msg['e'][0].get('v')

                if device_type == "light":
                    user_data['live_values']['light_actuator'] = value
                    self.logger.debug(f"Light actuator state updated: {value}%")
                elif device_type == "heater":
                    user_data['live_values']['heater_state'] = value
                    self.logger.debug(f"Heater actuator state updated: {value}")
                elif device_type == "fan":
                    user_data['live_values']['fan_state'] = value
                    self.logger.debug(f"Fan actuator state updated: {value}")
        except Exception as e:
            self.logger.warning(f"Invalid actuator payload for user {userid}: {e}")

    def _handle_preference_topic(self, topic, message_received):
        preference_kind, entity_id = _parse_preference_topic(topic)

        if preference_kind == "user":
            self._update_user_preferences(entity_id, message_received)
            return

        # Room preferences are now part of user cache, handled through user updates
        self.logger.warning(f"Preference topic: {topic}")

    def _update_user_preferences(self, userid, message_received):
        if "night_time" not in message_received and "morning_time" not in message_received:
            return

        user_cache = self.active_users_cache.get(userid)
        if not user_cache:
            self.logger.warning(f"User {userid} not found in cache, will fetch on next sensor event")
            return

        if "night_time" in message_received:
            user_cache["night_time"] = message_received["night_time"]
            self.logger.info(f"Updated night_time for user {userid}: {message_received['night_time']}")
        if "morning_time" in message_received:
            user_cache["morning_time"] = message_received["morning_time"]
            self.logger.info(f"Updated morning_time for user {userid}: {message_received['morning_time']}")

        self.logger.info(f"Current user preferences for {userid}: {user_cache}")


    def get_actuators_in_room(self, room_id):
        response = requests.get(f"{self.catalog_url}/getActuatorByRoom",
                                params={"room_id": room_id})
        if response.status_code == 200:
            try:
                data = response.json()
                actuatorslist=set()
                for actuator in data.get("actuators", []):
                    actuator_type = actuator.get("type")
                    actuatorslist.add(actuator_type)
                actuators=list(actuatorslist)
                return actuators
            except json.JSONDecodeError as e:
                self.logger.error(f"Error of decoding JSON for actuators in {room_id}: {e}")
                return []
        else:
            self.logger.error(
                f"Error in request to Catalog for actuators in {bedroomid}: {response.status_code} - {response.text}")
            return []

    def handle_temperature(self, message_received, room_actuator, desired_temperature, houseid, bedroomid):
        temp_value = float(message_received['e'][0]['v'])
        if desired_temperature is None:
            self.logger.warning(f"Desired temperature is None for room {bedroomid}, skipping temperature handling.")
            return

        tol = max(0.0, float(self.temperature_tolerance))
        desired_temperature = float(desired_temperature)

        # In-band comfort: force both HVAC actuators OFF to avoid oscillation.
        if abs(temp_value - desired_temperature) <= tol:
            base_topic = self.topic_publish[0]
            for device in ("fan", "heater"):
                if device not in room_actuator:
                    continue
                topic = base_topic.format(
                    houseID=houseid,
                    bedroomID=bedroomid,
                    device=device
                )
                self.publish({"action": 0, "timestamp": datetime.now().timestamp()}, command_topic=topic)
            return

        # Use prefer_fan flag from phase_manager if available
        prefer_fan = getattr(self.phase_manager, 'prefer_fan', True)
        action, device = _resolve_temperature_action(
            temp_value,
            desired_temperature,
            room_actuator,
            prefer_fan=prefer_fan,
            tolerance=tol
        )
        if action is None or device is None:
            return

        # CRITICAL: Ensure mutual exclusivity - only one HVAC device active at a time
        base_topic = self.topic_publish[0]

        # Send command to the target device
        command = {"action": action, "timestamp": datetime.now().timestamp()}
        topic = base_topic.format(houseID=houseid, bedroomID=bedroomid, device=device)
        self.publish(command, command_topic=topic)

        # Turn OFF the opposite device to prevent both being active simultaneously
        opposite_device = "heater" if device == "fan" else "fan"
        if opposite_device in room_actuator:
            off_command = {"action": 0, "timestamp": datetime.now().timestamp()}
            off_topic = base_topic.format(houseID=houseid, bedroomID=bedroomid, device=opposite_device)
            self.publish(off_command, command_topic=off_topic)

    def handle_presence(self, message_received, userid, houseid, bedroomid):
        presence_value = message_received['e'][0]['v']
        finish_sleep_topic = self.topic_publish[2].format(userid=userid)

        user_data = self.active_users_cache.get(userid)
        if not user_data:
            self.logger.warning(f"User {userid} not found in cache for presence handling")
            return

        # Track when user leaves bed
        if presence_value != 1:
            if user_data["live_values"].get("last_left_bed") is None:
                user_data["live_values"]["last_left_bed"] = datetime.now()
            else:
                seconds_out_of_bed = (datetime.now() - user_data["live_values"]["last_left_bed"]).total_seconds()
                if user_data.get("is_sleeping", False) and seconds_out_of_bed >= self.SLEEP_DETECTION_SECONDS:
                    user_data["is_sleeping"] = False
                    user_data["live_values"]["last_seen_bed"] = None
                    user_data["live_values"]["last_left_bed"] = None
                    self.publish({"action": "FINISH_SLEEP", "timestamp": str(datetime.now())}, command_topic=finish_sleep_topic)
                    self.logger.info(f"User {userid} finished sleep in {bedroomid}")
            return
        else:
            user_data["live_values"]["last_left_bed"] = None

        if user_data["live_values"].get("last_seen_bed") is None:
            user_data["live_values"]["last_seen_bed"] = datetime.now()
            return

        second_in_bed = (datetime.now() - user_data["live_values"]["last_seen_bed"]).total_seconds()
        if user_data.get("is_sleeping", False) or second_in_bed < self.SLEEP_DETECTION_SECONDS:
            return

        user_data["is_sleeping"] = True
        # Use heart_rate topic from config
        topic_heart = self.topic_publish[1].format(houseID=houseid, bedroomID=bedroomid)
        message = {"action": 1, "timestamp": str(datetime.now())}
        self.publish(message, command_topic=topic_heart)
        self.logger.info(f"User {userid} is now sleeping in {bedroomid}")

    def change_target_temperature_light(self, userid, target_temperature=None, target_light=None, phase=None):
        """
        Update the live targets for a user based on phase transitions.
        Publish light commands and phase updates via MQTT.
        """
        user_data = self.active_users_cache.get(userid)
        if not user_data:
            self.logger.warning(f"User {userid} not found in cache for target update")
            return

        self.logger.info(f"Updating targets for user {userid}: temp={target_temperature}, light={target_light}, phase={phase}")

        previous_light = user_data["live_targets"].get("light")
        previous_phase = user_data["live_values"].get("phase")
        phase_published = user_data["live_values"].get("phase_published", False)
        start_sleep_sent = user_data["live_values"].get("start_sleep_sent", False)

        if target_temperature is not None:
            user_data["live_targets"]["temperature"] = target_temperature
        if target_light is not None:
            user_data["live_targets"]["light"] = target_light
        if phase is not None:
            user_data["live_values"]["phase"] = phase

        houseid = user_data.get("house_id")
        bedroomid = user_data.get("active_room_id")

        # Publish light command: always on first call (previous_light is None) or when value changes
        if target_light is not None:
            new_value = int(round(max(0.0, min(100.0, float(target_light)))))
            old_value = None if previous_light is None else int(round(previous_light))
            if old_value is None or old_value != new_value:
                topic = f"House/{houseid}/Bedroom/{bedroomid}/actuator/light/command"
                command = {"action": "SET", "value": new_value}
                self.publish(command, command_topic=topic)
                self.logger.info(f"Sent SET command to light actuator: value={new_value}, phase={phase}, topic={topic}")

        # Publish phase: on first publish ever, or when phase changes, or during active transitions
        is_transition = phase in ("WIND_DOWN", "WAKE_UP")
        if phase is not None and (not phase_published or phase != previous_phase or is_transition):
            phase_topic = self.topic_publish[4].format(houseid=houseid, bedroomid=bedroomid)
            phase_data = {
                "bn": f"{houseid}:{bedroomid}:phase",
                "e": [{"n": "Phase", "v": phase, "t": time.time()}]
            }
            self.publish(phase_data, command_topic=phase_topic)
            user_data["live_values"]["phase_published"] = True
            self.logger.info(f"Published phase update: {phase} to topic {phase_topic}")

            sensor_ts = user_data['live_values'].get('sensor_ts')
            ts_str = str(sensor_ts) if sensor_ts else str(datetime.now())

            # START_SLEEP: send exactly once per night (first transition into SLEEP)
            if phase == "SLEEP" and not start_sleep_sent:
                start_topic = self.topic_publish[3].format(userid=userid)
                self.publish({"action": "START_SLEEP", "timestamp": ts_str}, command_topic=start_topic)
                user_data["live_values"]["start_sleep_sent"] = True
                self.logger.info(f"Published START_SLEEP for user {userid} at {ts_str}")

            # FINISH_SLEEP: send once when leaving SLEEP (→ WAKE_UP or DAY)
            if previous_phase == "SLEEP" and phase != "SLEEP":
                finish_topic = self.topic_publish[2].format(userid=userid)
                self.publish({"action": "FINISH_SLEEP", "timestamp": ts_str}, command_topic=finish_topic)
                user_data["live_values"]["start_sleep_sent"] = False  # reset for next night
                self.logger.info(f"Published FINISH_SLEEP for user {userid} at {ts_str}")

if __name__ == "__main__":
    # Configure logging before any usage - DEBUG MODE ENABLED
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
