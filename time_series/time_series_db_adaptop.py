import json
import logging
import sys

import cherrypy

from common import catalog_client
from common.MQTT.MyMQTT import MyMQTT
from common.common import json_error_page
from time_series.time_series_db import TimeSeriesDB

# Configure logging
logger = logging.getLogger(__name__)


def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")

def _load_json_body():
    body = cherrypy.request.body.read()
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in request body: {e}")
        raise cherrypy.HTTPError(400, "Invalid JSON format")

def checkSenML(newmeasurament):
    required_top = ["bn", "e"]
    required_event = ["n", "u", "t", "v"]

    if not all(k in newmeasurament for k in required_top):
        raise cherrypy.HTTPError(400, "Missing bn or e")

    if not isinstance(newmeasurament["e"], list) or len(newmeasurament["e"]) == 0:
        raise cherrypy.HTTPError(400, "Field 'e' must be a non-empty list")

    if not all(all(field in event for field in required_event)
               for event in newmeasurament["e"]):
        raise cherrypy.HTTPError(400, "Missing required fields inside 'e'")
    return  True

class TimeSeriesDBAdapter:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog = catalog_client.CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)
        self.clientID=conf['MQTT']['clientID']
        self.broker=conf['MQTT']['broker']
        self.port=conf['MQTT']['port']
        self.topic_subscribe=conf['MQTT']['topic_subscribe']
        self.mqtt_client_subscriber = MyMQTT(self.clientID, self.broker, self.port, self)

        try:
            self.db = TimeSeriesDB(conf)
            self.catalog.register()
            self.startClient()
            if not self.db.health_check():
                logger.critical("Unable to connect to the database.")
                self.catalog.stop_background_loop()
        except Exception as e:
            logger.error(f"Error initializing TimeSeriesDBAdapter: {e}")
            raise
    # --------------------------------------------------------
    # POST METHOD - Add new resources
    # --------------------------------------------------------
    def POST(self, *uri, **params):
        pass

    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, Users, or Bedrooms."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "getSensorByRoom": self._get_sensor_by_room,
            "getSensorByType": self._get_sensor_by_type,
            "getSensorByRoomAndType": self._get_sensor_by_room_and_type,
            "getSensorById": self._get_sensor_by_id,
            "getAllSensors": self._get_all_sensors,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)



    def _get_sensor_by_room(self, params):
        room_id = params.get("room_id")
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'room_id' parameter")
        return self.db.get_sensor_by_room(room_id)
    def _get_sensor_by_type(self, params):
        sensor_type = params.get("sensor_type")
        if not sensor_type:
            raise cherrypy.HTTPError(400, "Missing 'sensor_type' parameter")
        return self.db.get_sensor_by_type(sensor_type)
    def _get_sensor_by_room_and_type(self, params):
        room_id = params.get("room_id")
        sensor_type = params.get("sensor_type")
        if not room_id or not sensor_type:
            raise cherrypy.HTTPError(400, "Missing 'room_id' or 'sensor_type' parameter")
        return self.db.get_sensor_by_room_and_type(room_id, sensor_type)
    def _get_sensor_by_id(self, params):
        sensor_id = params.get("sensor_id")
        if not sensor_id:
            raise cherrypy.HTTPError(400, "Missing 'sensor_id' parameter")
        return self.db.get_sensor_by_id(sensor_id)
    def _get_all_sensors(self, params):
        return self.db.get_all_sensors()
    def PUT(self, *uri, **params):
        pass
    def DELETE(self, *uri, **params):
        pass

    def notify(self, topic, payload):
        message_received = json.loads(payload)
        if checkSenML(message_received):
            logger.debug(f"Received valid SenML message: {message_received}")
            self.db.insert_data("measurements", message_received)
        else:
            logger.warning(f"Received invalid SenML message: {message_received}")

    def startClient(self):
        self.mqtt_client_subscriber.start()
        self.mqtt_client_subscriber.mySubscribe(self.topic_subscribe)

    def stopClient(self):
        # self.mqtt_client_subscriber.unsubscribe() -> not necessary because stop is already unsubscribing
        self.mqtt_client_subscriber.stop()


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
        time_series_db_adapter = TimeSeriesDBAdapter(full_conf)
        cherrypy.tree.mount(time_series_db_adapter, '/', conf)
        cherrypy.config.update({
            'server.socket_host': full_conf['serviceInfo']['host'],
            'server.socket_port': full_conf['serviceInfo']['port'],
            'error_page.default': json_error_page

        })

        cherrypy.engine.subscribe('start', time_series_db_adapter.catalog.start_background_loop)
        cherrypy.engine.subscribe('stop', time_series_db_adapter.catalog.stop_background_loop)
        cherrypy.engine.subscribe('stop', time_series_db_adapter.stopClient)
        cherrypy.engine.subscribe('stop', time_series_db_adapter.catalog.unregister)

        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)
