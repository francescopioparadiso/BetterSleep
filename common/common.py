import json
import logging

import cherrypy
from common.MQTT.MyMQTT import MyMQTT


def json_error_page(status, message, traceback, version):
    """Override CherryPy HTTPError to return JSON instead of HTML."""
    cherrypy.response.headers["Content-Type"] = "application/json"
    try:
        status_code = int(status.split(" ")[0])
    except (ValueError, IndexError):
        status_code = 500

    return json.dumps({
        "status": status_code,
        "error": message
    })


def mqtt_to_regex( topic):
    topic = topic.replace("+", "[^/]+")
    topic = topic.replace("#", ".*")
    return "^" + topic + "$"


def load_json_body():
    body = cherrypy.request.body.read()
    try:
        return json.loads(body)
    except Exception:
        raise cherrypy.HTTPError(400, "Invalid JSON format")


def init_mqtt_helper(service_instance, mqtt_info, logger=None, clientid_fallback=None):
    """
    Initialize MQTT client for any service.
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    try:

        # Get clientID with optional fallback
        client_id = mqtt_info.get('clientID')
        if not client_id and clientid_fallback:
            client_id = clientid_fallback()

        broker = mqtt_info.get('broker')
        port = mqtt_info.get('port')

        if not all([client_id, broker, port]):
            logger.error("Missing MQTT configuration: clientID, broker, or port")
            return None

        mqtt_client = MyMQTT(client_id, broker, port, service_instance)
        mqtt_client.start()

        if hasattr(service_instance, 'topic_subscribe_raw'):
            for topic in service_instance.topic_subscribe_raw:
                mqtt_client.mySubscribe(topic)
            logger.info(f"MQTT client initialized and subscribed to {service_instance.topic_subscribe_raw}")
        elif hasattr(service_instance, 'topic_subscribe_list'):
            for topic in service_instance.topic_subscribe_list:
                mqtt_client.mySubscribe(topic)
            logger.info(f"MQTT client initialized and subscribed to {service_instance.topic_subscribe_list}")
        else:
            logger.info(f"MQTT client initialized")

        return mqtt_client

    except Exception as e:
        logger.error(f"Error initializing MQTT client: {e}")
        return None



