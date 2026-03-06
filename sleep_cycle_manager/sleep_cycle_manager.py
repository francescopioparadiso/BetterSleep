import json
import sys
import threading
import logging
import cherrypy
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
        self.topic_subscribe = conf['MQTT']['topic_subscribe']
        try:
            self.mqtt_client = MyMQTT(self.clientID, self.broker, self.port, self)
            self.startClient()
            self.mqtt_client.mySubscribe(self.topic_subscribe)
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
        # 1. Decodifica il messaggio SenML ricevuto dai sensori simolati
        message_received = json.loads(payload)
        if data in topic:
            print(topic)
            houseid=topic.split("/")[1]
            bedroomid=topic.split("/")[3]
            sensor_type=topic.split("/")[5]
            sensorid=topic.split("/")[6]
            room_actuetor=["fan"] # we need to ask to the catalog for the actuators in the room, but for now we can assume that there is only one actuator in the room and it is the fan
            desiderate_temperature=25 # we need to ask to the catalog for the desiderate temperature, but for now we can assume that the desiderate temperature is 25 degrees
            if sensor_type == "ambient_temp":
                temp_value = message_received['e'][0]['v']
                if temp_value > desiderate_temperature and "fan" in room_actuetor:
                    if "fan" in room_actuetor:
                        command = {"action": "ON", "device": "fan", "timestamp": str(datetime.now())}
                        self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/fan")
                    elif "heater" in room_actuetor:
                        command = {"action": "OFF", "device": "heater", "timestamp": str(datetime.now())}
                        self.publish(command, command_topic=f"House/{houseid}/bedroom/{bedroomid}/actuators/heater")

                elif temp_value < desiderate_temperature :
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
