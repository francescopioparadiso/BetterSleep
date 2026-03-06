import json
import sys
import threading
import logging
import cherrypy
import requests

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from datetime import datetime
logger = logging.getLogger(__name__)

class SleepCycleManager:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self._stop_event = threading.Event()
        self._worker = None
        self.catalog_client = CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        self.catalog_client.register()
        self.clientID = conf['MQTT']['clientID']
        self.broker = conf['MQTT']['broker']
        self.port = conf['MQTT']['port']
        data, status, error = self.catalog_client.get(f"getEndpointUserService")
        self.user_service_endpoint = data.get("endpoint")
        if not self.user_service_endpoint:
            logger.error("User service endpoint not found in Catalog response")
            self.catalog_client.unregister()
            sys.exit(1)
        self.topic_subscribe = conf['MQTT']['topic_subscribe']
        self.room_preferences_cache = {}  # Cache per le preferenze delle stanze
        try:
            self.mqtt_client = MyMQTT(self.clientID, self.broker, self.port, self)
            self.startClient()
            self.mqtt_client.mySubscribe(self.topic_subscribe)
            self.mqtt_client.mySubscribe(f"UserService/ChangePreference/#")  # !!TODO topic for change preference i need to implement
        except Exception as e:
            logger.error(f"Error initializing MQTT client: {e}")
            self.catalog_client.unregister()
            sys.exit(1)

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def publish(self, message,command_topic=None):
        try:
            self.mqtt_client.publish(command_topic, json.dumps(message))
            logger.info(f"Published message to {topic_to_publish}: {message}")
        except Exception as e:
            logger.error(f"Error publishing message: {e}")


    def notify(self, topic, payload):
        message_received = json.loads(payload)
        # Wildcard-aware topic matching
        if "UserService/ChangePreference/" in topic:
            parts = topic.split("/")
            bedroomid = parts[2]
            msg = message_received
            if bedroomid in self.room_preferences_cache:
                logger.info(f"Update preferences for {bedroomid} in cache")
                new_prefs = msg.get("new_preferences", {})
                self.room_preferences_cache[bedroomid].update(new_prefs)
                logger.info(f"New preferences for {bedroomid}: {self.room_preferences_cache[bedroomid]}")
            return

        if topic.startswith("House/") and "/bedroom/" in topic and "/sensors/" in topic:

            houseid = topic.split("/")[1]
            bedroomid = topic.split("/")[3]
            sensor_type = topic.split("/")[5]
            room_data = self.get_room_preference(bedroomid)
            desiderate_temperature = room_data.get("temperature_night", 18)
            room_actuetor = room_data.get("actuators", [])
            if sensor_type == "ambient_temp":
                self.handle_temperature(message_received, room_actuetor, desiderate_temperature, houseid, bedroomid)
            if sensor_type == "light":
                pass
            if sensor_type == "presence":
                pass
            if sensor_type == "humidity":
                pass
            if sensor_type == "vibration":
                pass

    def get_room_preference(self, bedroomid):
        if bedroomid not in self.room_preferences_cache:
            logger.info(f"Cache miss for {bedroomid}, fetching from User Service")
            response = requests.get(f"{self.user_service_endpoint}/get_user_data", params={"bedroomid": bedroomid}) #!!TODO i need to implement
            """
               the date of output will be in json 
               preferences: {
               "temperature_night": 18,
               "temperature_morning": 22,
               "light_night": 0,
               "light_morning": 100,
               }
            """
            if response.status_code == 200:
                try:
                    data = response.json()
                    self.room_preferences_cache[bedroomid] = data.get("preferences", {})
                    self.room_preferences_cache[bedroomid]["actuators"] = self.get_actuators_in_room(bedroomid)
                    self.room_preferences_cache[bedroomid]["is_sleeping"] = False
                    self.room_preferences_cache[bedroomid]["last_seen_bed"] = None #!!TODO i need to implement the control of sleeping or not sleeping if more then 30 minutes the user is in bed we can consider him sleeping

                    logger.info(f"Cache updated for {bedroomid}: {self.room_preferences_cache[bedroomid]}")
                except json.JSONDecodeError as e:
                    logger.error(f"Error decoding JSON for {bedroomid}: {e}")
                    self.room_preferences_cache[bedroomid] = {}


            else:
                logger.error(f"Error in request to User Service for {bedroomid}: {response.status_code} - {response.text}")
                self.room_preferences_cache[bedroomid] = {}
        return self.room_preferences_cache[bedroomid]



    def get_actuators_in_room(self, bedroomid):
        response = requests.get(f"{self.catalog_url}/getActuatorsInRoom", params={"bedroomid": bedroomid}) #!!TODO i need to implement
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
            logger.error(f"Error in request to Catalog for actuators in {bedroomid}: {response.status_code} - {response.text}")
            return []

    def handle_temperature(self, message_received, room_actuetor, desiderate_temperature, houseid, bedroomid):
        temp_value = message_received['e'][0]['v']
        if temp_value > desiderate_temperature and "fan" in room_actuetor:
            if "fan" in room_actuetor:
                command = {"action": "ON", "device": "fan", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/fan")
            elif "heater" in room_actuetor:
                command = {"action": "OFF", "device": "heater", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/heater")

        elif temp_value < desiderate_temperature:
            if "fan" in room_actuetor:
                command = {"action": "OFF", "device": "fan", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/fan")
            elif "heater" in room_actuetor:
                command = {"action": "ON", "device": "heater", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/heater")
        else:
            if "fan" in room_actuetor:
                command = {"action": "OFF", "device": "fan", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/fan")
            elif "heater" in room_actuetor:
                command = {"action": "OFF", "device": "heater", "timestamp": str(datetime.now())}
                self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/heater")

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
