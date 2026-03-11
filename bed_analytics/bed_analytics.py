import json
import sys
import time
import threading
import logging
from datetime import datetime
import cherrypy
import os
import sys
import re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from common.common import json_error_page, mqtt_to_regex
logger = logging.getLogger(__name__)


class BedAnalytics:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self._stop_event = threading.Event()
        self._worker = None
        self.actualTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.catalog_client = CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        self.catalog_client.register()
        self.mqtt_client = None
        self.MQTT_info = conf['MQTT']
        self.topic_subscribe_raw = self.MQTT_info['topic_subscribe']  # Fix: define topic_subscribe_raw
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]

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

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON payload received on topic {topic}")
            return
        print(f"Received MQTT message on topic {topic}: {message_received}")

if __name__ == "__main__":
    # Standard CherryPy startup sequence
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
        bed_analytics = BedAnalytics(full_conf)
        bed_analytics.init_mqtt_client()  # Fix: initialize and start MQTT client
        cherrypy.tree.mount(bed_analytics, '/', conf)
        cherrypy.config.update({
            'server.socket_host': full_conf['serviceInfo']['host'],
            'server.socket_port': full_conf['serviceInfo']['port'],
            'error_page.default': json_error_page

        })

        cherrypy.engine.subscribe('start', bed_analytics.catalog_client.start_background_loop)
        cherrypy.engine.subscribe('stop', bed_analytics.catalog_client.stop_background_loop)
        cherrypy.engine.subscribe('stop', bed_analytics.catalog_client.unregister)

        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)
