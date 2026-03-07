import json
import sys
import logging
import cherrypy
import requests
import re

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from datetime import datetime

from common.common import mqtt_to_regex, json_error_page

logger = logging.getLogger(__name__)


def _resolve_temperature_action(temp_value, desired_temperature, room_actuators):
    if temp_value > desired_temperature:
        if "fan" in room_actuators:
            return "ON", "fan"
        if "heater" in room_actuators:
            return "OFF", "heater"
        return None, None

    if temp_value < desired_temperature:
        if "fan" in room_actuators:
            return "OFF", "fan"
        if "heater" in room_actuators:
            return "ON", "heater"
        return None, None

    if "fan" in room_actuators:
        return "OFF", "fan"
    if "heater" in room_actuators:
        return "OFF", "heater"
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

    # UserService/ChangePreference/User/{userID}/Preference/
    if len(parts) >= 5 and parts[2] == "User":
        return "user", parts[3]

    # UserService/ChangePreference/House/{houseID}/Bedroom/{bedroomID}/User/{userID}/Preference/
    if len(parts) >= 8 and parts[2] == "House":
        return "room", parts[5]

    return None, None


class SleepCycleManager:
    exposed = True
    SLEEP_DETECTION_SECONDS = 1800

    def __init__(self, conf):
        self.mqtt_client = None
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog_client = CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        self.catalog_client.register()
        self.MQTT_info = conf['MQTT']
        self.user_service_endpoint = self.get_endpoint_user_service()
        self.topic_subscribe_raw = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]
        # - User cache: sleep-related data shared across all rooms (user can sleep in only one room at a time)
        # - Room cache: room-specific preferences (temperature, light settings)
        self.user_preferences_cache = {}  # {userid: {night_time, morning_time, is_sleeping, last_seen_bed}}
        self.room_preferences_cache = {}  # {bedroomid: {userid, houseid, temperature_night, temperature_morning, light_night, light_morning, actuators}}
        self.topic_publish = self.MQTT_info.get('topic_publish', )
        self.init_mqtt_client()

    def get_endpoint_user_service(self):
        data, status, error = self.catalog_client.get(f"getEndpointUserService")
        if status == 200 and data:
            endpoint = data.get("endpoint")
            if endpoint:
                logger.info(f"User service endpoint retrieved: {endpoint}")
                return endpoint
            else:
                logger.error("User service endpoint not found in Catalog response")
                return None
        else:
            logger.error(f"Error retrieving user service endpoint: {status} - {error}")
            return None

    def init_mqtt_client(self):
        client_id = self.MQTT_info['clientID']
        broker = self.MQTT_info['broker']
        port = self.MQTT_info['port']
        try:
            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.startClient()
            for topic in self.topic_subscribe_raw:
                self.mqtt_client.mySubscribe(topic)
            logger.info(f"MQTT client initialized and subscribed to {self.topic_subscribe_raw}")
        except Exception as e:
            logger.error(f"Error initializing MQTT client: {e}")
            self.catalog_client.unregister()
            sys.exit(1)

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def publish(self, message, command_topic=None):
        try:
            self.mqtt_client.publish(command_topic, json.dumps(message))
            logger.info(f"Published message to {command_topic}: {message}")
        except Exception as e:
            logger.error(f"Error publishing message: {e}")

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
            logger.info(f"Received message on topic {topic}: {message_received}")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON payload received on topic {topic}")
            return

        for index, regex in enumerate(self.topic_subscribe_regex):
            if not regex.match(topic):
                continue

            if index == 0:
                self._handle_sensor_topic(topic, message_received)
                return

            if index == 1:
                self._handle_preference_topic(topic, message_received)
                return

        logger.warning(f"Received message on unrecognized topic: {topic}")

    def _handle_sensor_topic(self, topic, message_received):
        sensor_data = _parse_sensor_topic(topic)
        if not sensor_data:
            logger.warning(f"Malformed sensor topic: {topic}")
            return

        houseid, bedroomid, sensor_type = sensor_data
        preferences = self.get_room_preference(bedroomid)
        if not preferences:
            logger.error(f"No preferences found for {bedroomid}, skipping message")
            return

        user_prefs = preferences.get('user_preferences', {})
        room_prefs = preferences.get('room_preferences', {})

        if sensor_type == "ambient_temp":
            is_sleeping = user_prefs.get("is_sleeping", False)
            desired_temperature = (
                room_prefs.get("temperature_night") if is_sleeping
                else room_prefs.get("temperature_morning")
            )
            room_actuators = room_prefs.get("actuators", [])
            self.handle_temperature(message_received, room_actuators, desired_temperature, houseid, bedroomid)
            return

        if sensor_type == "presence":
            self.handle_presence(message_received, user_prefs, room_prefs, houseid, bedroomid)

    def _handle_preference_topic(self, topic, message_received):
        preference_kind, entity_id = _parse_preference_topic(topic)

        if preference_kind == "user":
            self._update_user_preferences(entity_id, message_received)
            return

        if preference_kind == "room":
            self._update_room_preferences(entity_id, message_received)
            return

        logger.warning(f"Malformed preference topic: {topic}")

    def _update_user_preferences(self, userid, message_received):
        if "night_time" not in message_received and "morning_time" not in message_received:
            return

        user_cache = self.user_preferences_cache.get(userid)
        if not user_cache:
            logger.warning(f"User {userid} not found in cache, will fetch on next sensor event")
            return

        if "night_time" in message_received:
            user_cache["night_time"] = message_received["night_time"]
            logger.info(f"Updated night_time for user {userid}: {message_received['night_time']}")

        if "morning_time" in message_received:
            user_cache["morning_time"] = message_received["morning_time"]
            logger.info(f"Updated morning_time for user {userid}: {message_received['morning_time']}")

        logger.info(f"Current user preferences for {userid}: {user_cache}")

    def _update_room_preferences(self, bedroomid, message_received):
        updatable_keys = ["temperature_night", "temperature_morning", "light_night", "light_morning"]
        if not any(key in message_received for key in updatable_keys):
            return

        room_cache = self.room_preferences_cache.get(bedroomid)
        if not room_cache:
            logger.warning(f"Room {bedroomid} not found in cache, will fetch on next sensor event")
            return

        for key in updatable_keys:
            if key in message_received:
                room_cache[key] = message_received[key]
                logger.info(f"Updated {key} for room {bedroomid}: {message_received[key]}")

        logger.info(f"Current room preferences for {bedroomid}: {room_cache}")

    def get_room_preference(self, bedroomid):
        if bedroomid not in self.room_preferences_cache:
            self._fetch_and_cache_room_preference(bedroomid)

        room_prefs = self.room_preferences_cache.get(bedroomid)
        if not room_prefs:
            return None

        userid = room_prefs.get("userid")
        return {
            'user_preferences': self.user_preferences_cache.get(userid, {}),
            'room_preferences': room_prefs
        }

    def _fetch_and_cache_room_preference(self, bedroomid):
        logger.info(f"Cache miss for room {bedroomid}, fetching from User Service")
        response = requests.get(
            f"{self.user_service_endpoint}/getUserRoomPreferences",
            params={"bedroom_id": bedroomid}
        )

        if response.status_code != 200:
            logger.error(f"Error in request to User Service for {bedroomid}: {response.status_code} - {response.text}")
            self.room_preferences_cache[bedroomid] = {}
            return

        try:
            data = response.json()
            preferences = data.get("preferences", {})
            user_prefs = preferences.get("user_preferences", {})
            room_prefs = preferences.get("room_preferences", {})

            userid = user_prefs.get("user_id") or room_prefs.get("user_id")
            houseid = room_prefs.get("house_id")

            self.room_preferences_cache[bedroomid] = {
                "userid": userid,
                "houseid": houseid,
                "temperature_night": room_prefs.get("temperature_night"),
                "temperature_morning": room_prefs.get("temperature_morning"),
                "light_night": room_prefs.get("light_night"),
                "light_morning": room_prefs.get("light_morning"),
                "actuators": self.get_actuators_in_room(bedroomid)
            }

            if userid and userid not in self.user_preferences_cache:
                self.user_preferences_cache[userid] = {
                    "night_time": user_prefs.get("night_time"),
                    "morning_time": user_prefs.get("morning_time"),
                    "is_sleeping": False,
                    "last_seen_bed": None
                }
                logger.info(f"User cache updated for {userid}: {self.user_preferences_cache[userid]}")

            logger.info(f"Room cache updated for {bedroomid}: {self.room_preferences_cache[bedroomid]}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON for {bedroomid}: {e}")
            self.room_preferences_cache[bedroomid] = {}

    def get_actuators_in_room(self, bedroomid):
        response = requests.get(f"{self.catalog_url}/getActuatorsInRoom",
                                params={"bedroomid": bedroomid})
        if response.status_code == 200:
            try:
                data = response.json()
                actuators = data.get("actuators", [])
                logger.info(f"Actuators in {bedroomid}: {actuators}")
                return actuators
            except json.JSONDecodeError as e:
                logger.error(f"Error of decoding JSON for actuators in {bedroomid}: {e}")
                return []
        else:
            logger.error(
                f"Error in request to Catalog for actuators in {bedroomid}: {response.status_code} - {response.text}")
            return []

    def handle_temperature(self, message_received, room_actuetor, desiderate_temperature, houseid, bedroomid):
        temp_value = message_received['e'][0]['v']
        room_actuators = room_actuetor
        desired_temperature = desiderate_temperature
        base_topic = self.topic_publish[0].replace("{houseid}", houseid).replace("{bedroomid}", bedroomid)

        action, device = _resolve_temperature_action(temp_value, desired_temperature, room_actuators)
        if not action or not device:
            return

        self.publish(_build_command(action, device), command_topic=f"{base_topic}/{device}")

    def handle_presence(self, message_received, user_prefs, room_prefs, houseid, bedroomid):
        _ = user_prefs  # Preserved for signature compatibility.
        presence_value = message_received['e'][0]['v']
        userid = room_prefs.get("userid")

        if not userid or userid not in self.user_preferences_cache:
            logger.warning(f"User {userid} not found in cache for room {bedroomid}")
            return

        user_data = self.user_preferences_cache[userid]
        topic_to_publish = self.topic_publish[1].replace("{houseid}", houseid).replace("{bedroomid}", bedroomid)

        if presence_value != 1:
            user_data["last_seen_bed"] = None
            if user_data.get("is_sleeping", False):
                user_data["is_sleeping"] = False
                logger.info(f"User {userid} is now awake in {bedroomid}")
            return

        if user_data.get("last_seen_bed") is None:
            user_data["last_seen_bed"] = datetime.now()
            return

        second_in_bed = (datetime.now() - user_data["last_seen_bed"]).total_seconds()
        if user_data.get("is_sleeping", False) or second_in_bed < self.SLEEP_DETECTION_SECONDS:
            return

        user_data["is_sleeping"] = True
        message = {"action": "START_SLEEPING", "timestamp": str(datetime.now())}
        self.publish(message, command_topic=topic_to_publish)
        logger.info(f"User {userid} is now sleeping in {bedroomid}")


if __name__ == "__main__":
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
        sleep_cycle_manager = SleepCycleManager(full_conf)
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
