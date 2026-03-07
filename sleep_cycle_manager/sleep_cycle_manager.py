import json
import sys
import threading
import logging
import cherrypy
import requests
import re

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from datetime import datetime

logger = logging.getLogger(__name__)


def mqtt_to_regex(self, topic):
    topic = topic.replace("+", "[^/]+")
    topic = topic.replace("#", ".*")
    return "^" + topic + "$"


class SleepCycleManager:
    exposed = True

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
        self.room_preferences_cache = {}
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
        client_id = self.MQTT_info['client_id']
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
            logger.info(f"Published message to {topic_to_publish}: {message}")
        except Exception as e:
            logger.error(f"Error publishing message: {e}")

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON payload received on topic {topic}")
            return

        for i, regex in enumerate(self.topic_subscribe_regex):
            if regex.match(topic):
                # i == 0 → sensor data
                # i == 1 → user preference update
                if i == 0:  # sensor data
                    parts = topic.split("/")
                    if len(parts) < 7:
                        logger.warning(f"Malformed sensor topic: {topic}")
                        return
                    houseid = parts[1]
                    bedroomid = parts[3]
                    sensor_type = parts[5]
                    room_data = self.get_room_preference(bedroomid)
                    if not room_data:
                        logger.error(f"No room data found for {bedroomid}, skipping message")
                        return
                    if sensor_type == "ambient_temp":
                        desired_temperature = (
                            room_data.get("temperature_night") if room_data.get("is_sleeping")
                            else room_data.get("temperature_morning")
                        )
                        room_actuators = room_data.get("actuators", [])
                        self.handle_temperature(message_received, room_actuators, desired_temperature, houseid,
                                                bedroomid)
                    elif sensor_type == "presence":
                        self.handle_presence(message_received, room_data, houseid, bedroomid)
                    return
            elif i == 1:
                parts = topic.split("/")
                bedroomid = parts[2] if len(parts) > 2 else None
                if bedroomid and bedroomid in self.room_preferences_cache:
                    logger.info(f"Update preferences for {bedroomid} in cache")
                    new_prefs = message_received.get("new_preferences", {})
                    self.room_preferences_cache[bedroomid].update(new_prefs)
                    logger.info(f"New preferences for {bedroomid}: {self.room_preferences_cache[bedroomid]}")
                return

            logger.warning(f"Received message on unrecognized topic: {topic}")

    def get_room_preference(self, bedroomid):
        if bedroomid not in self.room_preferences_cache:
            logger.info(f"Cache miss for {bedroomid}, fetching from User Service")
            response = requests.get(f"{self.user_service_endpoint}/get_user_data",
                                    params={"bedroomid": bedroomid})  # !!TODO i need to implement
            """
               the date of output will be in json 
               preferences: {
               "temperature_night": 18,
               "temperature_morning": 22,
               "light_night": 0,
               "light_morning": 100,
               "night_time": "22:00",
                "morning_time": "07:00"
               }
            """
            if response.status_code == 200:
                try:
                    data = response.json()
                    self.room_preferences_cache[bedroomid] = data.get("preferences", {})
                    self.room_preferences_cache[bedroomid]["actuators"] = self.get_actuators_in_room(bedroomid)
                    self.room_preferences_cache[bedroomid]["is_sleeping"] = False
                    self.room_preferences_cache[bedroomid]["last_seen_bed"] = None

                    logger.info(f"Cache updated for {bedroomid}: {self.room_preferences_cache[bedroomid]}")
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding JSON for {bedroomid}: {e}")
                    self.room_preferences_cache[bedroomid] = {}


            else:
                logger.error(
                    f"Error in request to User Service for {bedroomid}: {response.status_code} - {response.text}")
                self.room_preferences_cache[bedroomid] = {}
        return self.room_preferences_cache[bedroomid]

    def get_actuators_in_room(self, bedroomid):
        response = requests.get(f"{self.catalog_url}/getActuatorsInRoom",
                                params={"bedroomid": bedroomid})  # !!TODO i need to implement
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
        topic_to_publish = self.topic_publish[0].replace("{houseid}", houseid).replace("{bedroomid}", bedroomid)
        if temp_value > desiderate_temperature and "fan" in room_actuetor:
            if "fan" in room_actuetor:
                command = {"action": "ON", "device": "fan", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"{topic_to_publish}/fan")
            elif "heater" in room_actuetor:
                command = {"action": "OFF", "device": "heater", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"{topic_to_publish}/heater")

        elif temp_value < desiderate_temperature:
            if "fan" in room_actuetor:
                command = {"action": "OFF", "device": "fan", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"{topic_to_publish}/fan")
            elif "heater" in room_actuetor:
                command = {"action": "ON", "device": "heater", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"{topic_to_publish}/heater")
        else:
            if "fan" in room_actuetor:
                command = {"action": "OFF", "device": "fan", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"{topic_to_publish}/fan")
            elif "heater" in room_actuetor:
                command = {"action": "OFF", "device": "heater", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"{topic_to_publish}/heater")

    def handle_presence(self, message_received, room_data, houseid, bedroomid):
        presence_value = message_received['e'][0]['v']
        topic_to_publish = self.topic_publish[1].replace("{houseid}", houseid).replace("{bedroomid}", bedroomid)
        if presence_value == 1:
            if room_data.get("last_seen_bed") is None:
                room_data["last_seen_bed"] = now
                return
            second_in_bed = (datetime.now() - room_data["last_seen_bed"]).total_seconds() if room_data.get(
                "last_seen_bed") else 0
            if not room_data.get("is_sleeping",
                                 False) and second_in_bed >= 1800:  # user more than 30 minutes in bed we can consider him sleeping
                room_data["is_sleeping"] = True
                message = {"action": "START_SLEEPING", "timestamp": str(datetime.now())}
                self.publish(message,
                             command_topic=topic_to_publish)  # !!TODO i need to implement the topic for start sleeping
                logger.info(f"User is now sleeping in {bedroomid}")
        else:
            room_data["last_seen_bed"] = None
            if room_data.get("is_sleeping", False):
                room_data["is_sleeping"] = False
                logger.info(f"User is now awake in {bedroomid}")


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
            'server.socket_port': full_conf['serviceInfo']['port']
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
