import json
import logging
import re

import cherrypy

from common import catalog_client
from common.common import json_error_page, mqtt_to_regex, init_mqtt_helper
from mongo_db import MongoDB

# Configure logging
logger = logging.getLogger(__name__)


def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")


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


def _json_response(data):
    cherrypy.response.headers['Content-Type'] = 'application/json'
    return json.dumps(data).encode('utf-8')


class TimeSeries:
    exposed = True

    def __init__(self, conf):
        self.logger = logger
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog = catalog_client.CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)
        self.MQTT_info = conf['MQTT']
        self.mqtt_client = None
        self.topic_subscribe_raw = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]

        try:
            self.db = MongoDB(conf)
            self.init_mqtt_client()
            self.catalog.register()
            if not self.db.health_check():
                logger.critical("Unable to connect to the database.")
                self.catalog.stop_background_loop()
        except Exception as e:
            logger.error(f"Error initializing TimeSeriesDBAdapter: {e}")
            raise

#MQTT
    def init_mqtt_client(self):
        try:
            self.mqtt_client = init_mqtt_helper(self, self.MQTT_info, self.logger)
            if self.mqtt_client is None:
                self.catalog.unregister()
                raise SystemExit(1)
        except Exception as e:
            self.logger.error(f"Error initializing MQTT client: {e}")
            self.catalog.unregister()
            raise SystemExit(1)

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON payload received on topic {topic}: {e}")
            return
        if "sensor" in topic:
            if checkSenML(message_received):
                logger.debug(f"Received valid SenML message: {message_received}")
                self.db.insert_measurements_data("measurements", message_received)
            else:
                logger.warning(f"Received invalid SenML message: {message_received}")
        elif "BedAnalitics" in topic:
            logger.debug(f"Received sleep analytics message: {message_received}")
            if "user_id" in message_received  :
                self.db.insert_sleep_score(message_received)
                logger.info(f"Sleep analytics saved for user {message_received.get('user_id')}")
            else:
                logger.warning(f"Sleep analytics message missing user_id : {message_received}")

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()


# REST
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
            "getSensorDataByRoomAndTimeRange": self._get_sensor_data_by_room_and_time_range,
            "getSleepScoresByUser": self._get_sleep_scores_by_user,
            "getSleepAnalyticsByUser": self._get_sleep_analytics_by_user,
            "getLatestSleepAnalytics": self._get_latest_sleep_analytics,
            "getSleepAnalyticsByDate": self._get_sleep_analytics_by_date,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _get_sensor_by_room(self, params):
        room_id = params.get("room_id")
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'room_id' parameter")
        return _json_response(self.db.get_sensor_by_room(room_id))

    def _get_sensor_by_type(self, params):
        sensor_type = params.get("sensor_type")
        if not sensor_type:
            raise cherrypy.HTTPError(400, "Missing 'sensor_type' parameter")
        return _json_response(self.db.get_sensor_by_type(sensor_type))

    def _get_sensor_by_room_and_type(self, params):
        room_id = params.get("room_id")
        sensor_type = params.get("sensor_type")
        if not room_id or not sensor_type:
            raise cherrypy.HTTPError(400, "Missing 'room_id' or 'sensor_type' parameter")
        return _json_response(self.db.get_sensor_by_room_and_type(room_id, sensor_type))

    def _get_sensor_by_id(self, params):
        sensor_id = params.get("sensor_id")
        if not sensor_id:
            raise cherrypy.HTTPError(400, "Missing 'sensor_id' parameter")
        return _json_response(self.db.get_sensor_by_id(sensor_id))

    def _get_sensor_data_by_room_and_time_range(self, params):
        room_id = params.get("room_id")
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        if not room_id or not start_time or not end_time:
            raise cherrypy.HTTPError(400, "Missing 'room_id', 'start_time', or 'end_time' parameter")
        return _json_response(self.db.get_sensor_data_by_room_and_time_range(room_id, start_time, end_time))

    def _get_sleep_scores_by_user(self, params):
        user_id = params.get("user_id")
        if not user_id:
            raise cherrypy.HTTPError(400, "Missing 'user_id' parameter")
        return _json_response(self.db.get_sleep_scores_by_user(user_id))

    def _get_sleep_analytics_by_user(self, params):
        user_id = params.get("user_id")
        if not user_id:
            raise cherrypy.HTTPError(400, "Missing 'user_id' parameter")
        limit = int(params.get("limit", 30))
        return _json_response(self.db.get_sleep_analytics_by_user(user_id, limit))

    def _get_sleep_analytics_by_date(self, params):
        user_id = params.get("user_id")
        date_str = params.get("date")
        if not user_id or not date_str:
            raise cherrypy.HTTPError(400, "Missing 'user_id' or 'date' parameter")
        result = self.db.get_sleep_analytics_by_date(user_id, date_str)
        if result is None:
            return _json_response({"error": "No sleep analytics found for user on this date"})
        return _json_response(result)

    def _get_latest_sleep_analytics(self, params):
        user_id = params.get("user_id")
        if not user_id:
            raise cherrypy.HTTPError(400, "Missing 'user_id' parameter")
        result = self.db.get_latest_sleep_analytics(user_id)
        if result is None:
            return _json_response({"error": "No sleep analytics found for user"})
        return _json_response(result)

    def _get_all_sensors(self, params):
        return _json_response(self.db.get_all_sensors())



if __name__ == "__main__":
    # Standard CherryPy startup sequence
    try:
        with open("conf.json", "r") as f:
            full_conf = json.load(f)
    except FileNotFoundError:
        logger.error("Configuration file 'conf.json' not found")
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in 'conf.json': {e}")
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Error reading configuration file: {e}")
        raise SystemExit(1)

    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}

    try:
        time_series_db_adapter = TimeSeries(full_conf)
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
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        raise SystemExit(1)
