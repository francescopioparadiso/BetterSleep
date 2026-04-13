import json
import logging
import cherrypy
import threading
import time
from common.common import json_error_page, load_json_body, init_mqtt_helper
from mongo_db import MongoDBAdapter



logger = logging.getLogger(__name__)



def check_if_is_a_service(new_service):
    """Validate that the service contains all required fields."""
    required_fields = ['serviceID','name','type','endpoint']
    require_fields(new_service, required_fields)


def check_if_is_a_sensor(new_sensor):
    """Validate that the sensor contains all required fields."""
    required_fields = ['sensorID','name','type']
    require_fields(new_sensor, required_fields)

def check_if_is_an_actuator(new_actuator):
    """Validate that the actuator contains all required fields."""
    required_fields = ['ActuatorID','name','type','endpoint']
    require_fields(new_actuator, required_fields)

def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")


class Catalog:

    exposed = True

    def __init__(self, db_adaptor, cleanup_interval_s=30, service_ttl_s=60, mqtt_conf=None):
        self.db = db_adaptor
        self.cleanup_interval_s = cleanup_interval_s
        self.service_ttl_s = service_ttl_s
        self._stop_event = threading.Event()
        self._worker = None
        self.mqtt_client = None
        self.mqtt_topic_actuator_added = None
        self.mqtt_topic_actuator_removed = None

        self._init_mqtt(mqtt_conf or {})

    def _init_mqtt(self, mqtt_conf):
        try:
            topics = mqtt_conf.get("topic_publish", {})

            if len(topics) >= 1:
                self.mqtt_topic_actuator_added = topics[0]
            if len(topics) >= 2:
                self.mqtt_topic_actuator_removed = topics[1]

            self.mqtt_client = init_mqtt_helper(
                self,
                mqtt_conf,
                logger=logger,
                clientid_fallback=lambda: mqtt_conf.get("clientID", "CatalogServicePublisher"),
            )
            if self.mqtt_client and (self.mqtt_topic_actuator_added or self.mqtt_topic_actuator_removed):
                logger.info(
                    f"MQTT publisher initialised (broker={mqtt_conf.get('broker')}:{mqtt_conf.get('port')}, "
                    f"topics={[t for t in [self.mqtt_topic_actuator_added, self.mqtt_topic_actuator_removed] if t]})"
                )
            elif not self.mqtt_client:
                logger.warning("MQTT publishing disabled: missing/invalid MQTT config")
        except Exception as e:
            logger.error(f"Failed to initialise MQTT publisher: {e}")
            self.mqtt_client = None

    def start_cleanup_loop(self):
        if self._worker is not None:
            return

        def _loop():
            while not self._stop_event.is_set():
                try:
                    deleted, stale_actuators = self.db.delete_stale(self.service_ttl_s)
                    if deleted > 0:
                        print(f"Removed {deleted} stale services (ttl={self.service_ttl_s}s)")
                    if stale_actuators:
                        for act in stale_actuators:
                            self.publish_actuator_removed(act)
                except Exception as e:
                    print(f"Error during cleanup loop: {e}")
                time.sleep(self.cleanup_interval_s)

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_cleanup_loop(self):
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=10)
            self._worker = None

    def stop_mqtt(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.stop()
            except Exception as e:
                logger.error(f"Error stopping MQTT client: {e}")
            self.mqtt_client = None

    # POST METHOD - Create new resources
    def POST(self, *uri, **params):
        """Handle POST requests to add new Services, Devices, or Users."""
        if not uri:
            print("POST request with no endpoint specified")
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "addService": self._post_add_service,
            "addSensor": self._post_add_sensor,
            "addActuator": self._post_add_actuator,
        }
        handler = handlers.get(uri[0])
        if not handler:
            print(f"POST handler not found for endpoint: {uri[0]}")
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _post_add_service(self):
        """Add a new service to the catalog."""
        try:
            new_service = load_json_body()
            check_if_is_a_service(new_service)
            new_service['last_update'] = time.time()
            success = self.db.insert_service(new_service)

            if success:
                return json.dumps({"status": "success", "message": "Service Added"})

            print(f"Service ID {new_service.get('serviceID')} already exists")
            raise cherrypy.HTTPError(409, "The Service ID already exists")
        except Exception as e:
            print(f"Error in _post_add_service: {e}")
            raise

    def _post_add_sensor(self):
        """Add a new sensor to the catalog."""
        new_sensor = load_json_body()
        check_if_is_a_sensor(new_sensor)
        new_sensor['last_update'] = time.time()

        success = self.db.insert_sensor(new_sensor)
        if success:
            return json.dumps({"status": "success", "message": "Sensor Added"})
        raise cherrypy.HTTPError(409, "The Sensor ID already exists")
    def _post_add_actuator(self):
        """Add a new actuator to the catalog."""
        new_actuator = load_json_body()
        check_if_is_an_actuator(new_actuator)
        new_actuator['last_update'] = time.time()
        success = self.db.insert_actuator(new_actuator)
        if success:
            self.publish_actuator_added(new_actuator)
            return json.dumps({"status": "success", "message": "Actuator Added"})
        raise cherrypy.HTTPError(409, "The Actuator ID already exists")
    # PUT METHOD - Update existing resources
    def PUT(self, *uri, **params):
        """Handle PUT requests to update Services, Devices, or Users."""
        logger.info(f"PUT method called with uri={uri}, params={params}")
        if not uri:
            print("PUT request with no endpoint specified")
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "updateService": self._put_update_service,
            "updateServiceLastUpdate": self._put_update_service_last_update,
            "updateSensorLastUpdate": self._put_update_sensor_last_update,
            "updateActuatorLastUpdate": self._put_update_actuator_last_update,
        }
        handler = handlers.get(uri[0])
        logger.info(f"Looking for handler: {uri[0]}, found: {handler is not None}")
        if not handler:
            print(f"Handler not found for endpoint: {uri[0]}")
            raise cherrypy.HTTPError(404, "Endpoint not found")
        logger.info(f"Calling handler for {uri[0]}")
        return handler()

    def _put_update_service(self):
        """Update an existing service in the catalog."""
        updated_service = load_json_body()
        check_if_is_a_service(updated_service)
        updated_service['last_update'] = time.time()

        success = self.db.update(updated_service)
        if success:
            return json.dumps({"status": "success", "message": "Service updated"})
        print(f"Update failed for serviceID {updated_service.get('serviceID')}")
        raise cherrypy.HTTPError(404, "The Service ID does not exist")

    def _put_update_service_last_update(self):
        """Update the last_update timestamp of a service."""
        try:
            updated_service = load_json_body()
            require_fields(updated_service, ['serviceID'])
            updated_service['last_update'] = time.time()

            success = self.db.update_service_last_update(int(updated_service['serviceID']), updated_service['last_update'])
            if success:
                return json.dumps({"status": "success", "message": "Service last_update updated"})

            print(f"Update failed for serviceID {updated_service.get('serviceID')} - service not found")
            raise cherrypy.HTTPError(404, "The Service ID does not exist")
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            print(f"Error in _put_update_service_last_update: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _put_update_sensor_last_update(self):
        """Update the last_update timestamp of a sensor."""
        updated_sensor = load_json_body()
        sensor_id = updated_sensor.get('sensorID') or updated_sensor.get('serviceID')
        if not sensor_id:
            raise cherrypy.HTTPError(400, "Missing 'sensorID' or 'serviceID'")
        success = self.db.update_sensor_last_update(int(sensor_id), time.time())
        if success:
            return json.dumps({"status": "success", "message": "Sensor last_update updated"})
        raise cherrypy.HTTPError(404, "The Sensor ID does not exist")

    def _put_update_actuator_last_update(self):
        """Update the last_update timestamp of an actuator."""
        updated_actuator = load_json_body()
        require_fields(updated_actuator, ['ActuatorID'])
        success = self.db.update_actuator_last_update(int(updated_actuator['ActuatorID']), time.time())
        if success:
            return json.dumps({"status": "success", "message": "Actuator last_update updated"})
        raise cherrypy.HTTPError(404, "The Actuator ID does not exist")

    # DELETE METHOD - Remove resources
    def DELETE(self, *uri, **params):
        """Handle DELETE requests to remove Services, Devices, Users, or Bedrooms."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "removeService": self._delete_remove_service,
            "removeSensor": self._delete_remove_sensor,
            "removeActuator": self._delete_remove_actuator,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _delete_remove_service(self, params):
        """Delete a service by serviceID."""
        service_id = params.get('serviceID')
        if not service_id:
            raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")
        success = self.db.delete_service(int(service_id))
        if success:
            return json.dumps({"status": "success", "message": "Service Deleted"})
        raise cherrypy.HTTPError(404, "Service not found")

    def _delete_remove_sensor(self, params):
        """Delete a sensor by serviceID and optional roomID."""
        service_id = params.get('sensorID')
        room_id = params.get('roomID')
        if not service_id:
            raise cherrypy.HTTPError(400, "Missing 'sensorID' parameter")
        # Pass room_id to delete_sensor to scope deletion to specific room when provided
        success = self.db.delete_sensor(int(service_id), int(room_id) if room_id else None)
        if success:
            return json.dumps({"status": "success", "message": "Sensor Deleted"})
        raise cherrypy.HTTPError(404, "Sensor not found")
    def _delete_remove_actuator(self, params):
        """Delete an actuator by serviceID."""
        actuator_id = params.get('ActuatorID')
        room_id = params.get('roomID')
        if not actuator_id:
            raise cherrypy.HTTPError(400, "Missing 'ActuatorID' parameter")
        success, doc = self.db.delete_actuator(int(actuator_id), int(room_id) if room_id else None)
        if success:
            self.publish_actuator_removed(doc or {"ActuatorID": actuator_id, "roomID": room_id})
            return json.dumps({"status": "success", "message": "Actuator Deleted"})
        raise cherrypy.HTTPError(404, "Actuator not found")

    # GET METHOD - Retrieve resources
    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, Users, or Bedrooms."""
        logger.info(f"GET method called with uri={uri}, params={params}")
        if not uri:
            print("GET request with no endpoint specified")
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        if uri == ("catalog", "services", "time_series"):
            return self._get_endpoint_Time_series_DB(params)

        handlers = {
            "getAllServices": self._get_all_services,
            "getService": self._get_service,
            "getEndpointTimeSeries": self._get_endpoint_Time_series_DB,
            "getEndpointUserService": self._get_endpoint_user_service,
            "getSensorByRoom": self._get_sensor_by_room,
            "getActuatorByRoom": self._get_actuator_by_room

        }
        handler = handlers.get(uri[0])
        if not handler:
            print(f"GET handler not found for endpoint: {uri[0]}")
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _get_endpoint_Time_series_DB(self, params=None):
        """Get the endpoint of the TimeSeriesDB service."""
        try:
            raw_scope = (params or {}).get("scope", "internal")
            scope = str(raw_scope).strip().lower()
            if scope not in {"internal", "external"}:
                raise cherrypy.HTTPError(400, "Invalid 'scope' parameter. Allowed values: internal, external")

            endpoint = self.db.get_endpoint_Time_series_DB(scope=scope)
            if endpoint:
                return json.dumps({"status": "success", "scope": scope, "endpoint": endpoint})
            print("TimeSeriesDB service not found")
            raise cherrypy.HTTPError(404, "TimeSeriesDB service not found")
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            print(f"Error retrieving TimeSeriesDB endpoint: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_endpoint_user_service(self, params=None):
        """Get the endpoint of the UserService."""
        try:
            endpoint = self.db.get_endpoint_user_service()
            if endpoint:
                return json.dumps({"status": "success", "endpoint": endpoint})
            print("UserService not found")
            raise cherrypy.HTTPError(404, "UserService not found")
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            print(f"Error retrieving UserService endpoint: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_all_services(self, params):
        """Get all services from the catalog (for debugging)."""
        try:
            services = self.db.get_all_services()
            services_json = []
            for service in services:
                service['_id'] = str(service.get('_id', ''))
                services_json.append(service)
            return json.dumps({"status": "success", "count": len(services), "services": services_json})
        except Exception as e:
            print(f"Error retrieving all services: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_service(self, params):
        """Get a specific service by serviceID."""
        service_id = params.get('serviceID')
        if not service_id:
            raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")
        try:
            service = self.db.get_service(service_id)
            if service:
                service['_id'] = str(service.get('_id', ''))
                return json.dumps({"status": "success", "service": service})
            print(f"Service {service_id} not found")
            raise cherrypy.HTTPError(404, f"Service {service_id} not found")
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            print(f"Error retrieving service {service_id}: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")
    def _get_sensor_by_room(self, params):
        """Get sensors by roomID."""
        room_id = params.get('roomID')
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'roomID' parameter")
        try:
            sensors = self.db.get_sensor_by_room(room_id)
            sensors_json = []
            for sensor in sensors:
                sensor['_id'] = str(sensor.get('_id', ''))
                sensors_json.append(sensor)
            return json.dumps({"status": "success", "count": len(sensors), "sensors": sensors_json})
        except Exception as e:
            print(f"Error retrieving sensors for room {room_id}: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")
    def _get_actuator_by_room(self, params):
        """Get actuators by roomID."""
        room_id = params.get('room_id')
        if not room_id:
            raise cherrypy.HTTPError(400, "Missing 'roomID' parameter")
        try:
            actuators = self.db.get_actuator_by_room(room_id)
            actuators_json = []
            for actuator in actuators:
                actuator['_id'] = str(actuator.get('_id', ''))
                actuators_json.append(actuator)
            return json.dumps({"status": "success", "count": len(actuators), "actuators": actuators_json})
        except Exception as e:
            print(f"Error retrieving actuators for room {room_id}: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")


    def publish_actuator_added(self, new_actuator):
        if not self.mqtt_client or not self.mqtt_topic_actuator_added:
            logger.warning("MQTT publish skipped: client or topic not available")
            return

        room_id = new_actuator.get("roomID") or new_actuator.get("room_id")
        house_id = new_actuator.get("houseID") or new_actuator.get("house_id")
        actuator_id = new_actuator.get("ActuatorID") or new_actuator.get("actuatorID")
        actuator_type = new_actuator.get("type")

        if room_id is None or house_id is None:
            logger.warning("Actuator added without houseID/roomID; MQTT publication skipped")
            return

        topic = self.mqtt_topic_actuator_added.format(houseID=house_id, roomID=room_id)
        payload = {
            "house_id": house_id,
            "room_id": room_id,
            "actuator_id": actuator_id,
            "type": actuator_type,
            "name": new_actuator.get("name"),
        }
        try:
            self.mqtt_client.myPublish(topic, payload)
            logger.info(f"Published actuator-added event to {topic}: {payload}")
        except Exception as e:
            logger.error(f"Failed to publish actuator-added event: {e}")

    def publish_actuator_removed(self, actuator_info):
        if not self.mqtt_client or not self.mqtt_topic_actuator_removed:
            logger.warning("MQTT publish skipped: client or removal topic not available")
            return

        room_id = actuator_info.get("roomID") or actuator_info.get("room_id")
        house_id = actuator_info.get("houseID") or actuator_info.get("house_id")
        actuator_id = actuator_info.get("ActuatorID") or actuator_info.get("actuatorID")
        actuator_type = actuator_info.get("type")

        if room_id is None or house_id is None:
            logger.warning("Actuator removal without houseID/roomID; MQTT publication skipped")
            return

        topic = self.mqtt_topic_actuator_removed.format(houseID=house_id, roomID=room_id)
        payload = {
            "house_id": house_id,
            "room_id": room_id,
            "actuator_id": actuator_id,
            "type": actuator_type,
        }
        try:
            self.mqtt_client.myPublish(topic, payload)
            logger.info(f"Published actuator-removed event to {topic}: {payload}")
        except Exception as e:
            logger.error(f"Failed to publish actuator-removed event: {e}")


if __name__ == "__main__":
    # CherryPy Configuration
    conf = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.sessions.on': True,
        }
    }

    # Load Configuration from JSON
    try:
        with open("conf.json", "r") as f:
            full_conf = json.load(f)
            server_conf = full_conf['server']
            db_conf = full_conf['database']
            mqtt_conf = full_conf.get('MQTT', {})
            cleanup_conf = full_conf.get('service_cleanup', {})
            cleanup_interval_s = cleanup_conf.get('interval_seconds', 30)
            service_ttl_s = cleanup_conf.get('ttl_seconds', 60)
    except FileNotFoundError:
        logger.error("Configuration file 'conf.json' not found")
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Error reading conf.json: {e}")
        raise SystemExit(1)
    try:
        my_db_adaptor = MongoDBAdapter(db_conf)
    except Exception as e:
        logger.error(f"Failed to initialize database connection: {e}")
        raise SystemExit(1)
    try:
        catalog = Catalog(my_db_adaptor, cleanup_interval_s, service_ttl_s, mqtt_conf)
        cherrypy.tree.mount(catalog, '/', conf)

        # Configure Server Settings
        cherrypy.config.update({
            'server.socket_port': server_conf['port'],
            'server.socket_host': server_conf['host'],
            'error_page.default': json_error_page
        })

        print(f"Starting Catalog Service on {server_conf['host']}:{server_conf['port']}")
        cherrypy.engine.subscribe('start', catalog.start_cleanup_loop)
        cherrypy.engine.subscribe('stop', catalog.stop_cleanup_loop)
        cherrypy.engine.subscribe('stop', catalog.stop_mqtt)
        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing server configuration key: {e}")
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        raise SystemExit(1)
