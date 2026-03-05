import json
import sys
import logging
import cherrypy
import threading
import time
from mongo_db import MongoDBAdapter

# Configure logging with DEBUG level


logger = logging.getLogger(__name__)


# ============================================================
# VALIDATION FUNCTIONS
# ============================================================

def check_if_is_a_service(new_service):
    """Validate that the service contains all required fields."""
    required_fields = ['serviceID','name','type','endpoint','last_update']
    require_fields(new_service, required_fields)


def check_if_is_a_sensor(new_sensor):
    """Validate that the sensor contains all required fields."""
    required_fields = ['serviceID','name','type','endpoint','last_update']
    if new_sensor.get('type') != 'sensor':
        raise cherrypy.HTTPError(400, "Type must be 'sensor'")
    require_fields(new_sensor, required_fields)

def check_if_is_an_actuator(new_actuator):
    """Validate that the actuator contains all required fields."""
    required_fields = ['serviceID','name','type','endpoint','last_update']
    if new_actuator.get('type') != 'actuator':
        raise cherrypy.HTTPError(400, "Type must be 'actuator'")
    require_fields(new_actuator, required_fields)

def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")
# ============================================================
# CATALOG REST SERVICE
# ============================================================

def _load_json_body():
    body = cherrypy.request.body.read()
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in request body: {e}")
        raise cherrypy.HTTPError(400, "Invalid JSON format")
    except Exception as e:
        logger.error(f"Unexpected error parsing request body: {e}")
        raise cherrypy.HTTPError(400, "Error parsing request body")


class Catalog:

    exposed = True

    def __init__(self, db_adaptor, cleanup_interval_s=30, service_ttl_s=60):
        self.db = db_adaptor
        self.cleanup_interval_s = cleanup_interval_s
        self.service_ttl_s = service_ttl_s
        self._stop_event = threading.Event()
        self._worker = None

    def start_cleanup_loop(self):
        if self._worker is not None:
            return

        def _loop():
            while not self._stop_event.is_set():
                try:
                    deleted = self.db.delete_stale(self.service_ttl_s)
                    if deleted > 0:
                        print(f"Removed {deleted} stale services (ttl={self.service_ttl_s}s)")
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
            new_service = _load_json_body()
            check_if_is_a_service(new_service)
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
        new_sensor = _load_json_body()
        check_if_is_a_sensor(new_sensor)
        success = self.db.insert_sensor(new_sensor)
        if success:
            return json.dumps({"status": "success", "message": "Sensor Added"})
        raise cherrypy.HTTPError(409, "The Sensor ID already exists")
    def _post_add_actuator(self):
        """Add a new actuator to the catalog."""
        new_actuator = _load_json_body()
        check_if_is_an_actuator(new_actuator)
        success = self.db.insert_actuator(new_actuator)
        if success:
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
        updated_service = _load_json_body()
        check_if_is_a_service(updated_service)

        success = self.db.update(updated_service)
        if success:
            return json.dumps({"status": "success", "message": "Service updated"})
        print(f"Update failed for serviceID {updated_service.get('serviceID')}")
        raise cherrypy.HTTPError(404, "The Service ID does not exist")

    def _put_update_service_last_update(self):
        """Update the last_update timestamp of a service."""
        try:
            updated_service = _load_json_body()
            require_fields(updated_service, ['serviceID', 'last_update'])

            success = self.db.update_service_last_update(updated_service['serviceID'], updated_service['last_update'])
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
        updated_sensor = _load_json_body()
        require_fields(updated_sensor, ['serviceID', 'last_update'])
        success = self.db.update_sensor_last_update(updated_sensor['serviceID'], updated_sensor['last_update'])
        if success:
            return json.dumps({"status": "success", "message": "Sensor last_update updated"})
        raise cherrypy.HTTPError(404, "The Sensor ID does not exist")

    def _put_update_actuator_last_update(self):
        """Update the last_update timestamp of an actuator."""
        updated_actuator = _load_json_body()
        require_fields(updated_actuator, ['ActuatorID', 'last_update'])
        success = self.db.update_actuator_last_update(updated_actuator['ActuatorID'], updated_actuator['last_update'])
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

        success = self.db.delete_service(service_id)
        if success:
            return json.dumps({"status": "success", "message": "Service Deleted"})
        raise cherrypy.HTTPError(404, "Service not found")

    def _delete_remove_sensor(self, params):
        """Delete a sensor by serviceID."""
        service_id = params.get('serviceID')
        if not service_id:
            raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")
        success = self.db.delete_sensor(service_id)
        if success:
            return json.dumps({"status": "success", "message": "Sensor Deleted"})
        raise cherrypy.HTTPError(404, "Sensor not found")
    def _delete_remove_actuator(self, params):
        """Delete an actuator by serviceID."""
        actuator_id = params.get('serviceID')
        if not actuator_id:
            raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")
        success = self.db.delete_actuator(actuator_id)
        if success:
            return json.dumps({"status": "success", "message": "Actuator Deleted"})
        raise cherrypy.HTTPError(404, "Actuator not found")

    # GET METHOD - Retrieve resources
    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, Users, or Bedrooms."""
        logger.info(f"GET method called with uri={uri}, params={params}")
        if not uri:
            print("GET request with no endpoint specified")
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "getAllServices": self._get_all_services,
            "getService": self._get_service,
            "getEndpointTimeSeries": self._get_endpoint_Time_series_DB,
            "getEndpointUserService": self._get_endpoint_user_service,

        }
        handler = handlers.get(uri[0])
        if not handler:
            print(f"GET handler not found for endpoint: {uri[0]}")
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _get_endpoint_Time_series_DB(self, params=None):
        """Get the endpoint of the TimeSeriesDB service."""
        try:
            endpoint = self.db.get_endpoint_Time_series_DB()
            if endpoint:
                return json.dumps({"status": "success", "endpoint": endpoint})
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
            cleanup_conf = full_conf.get('service_cleanup', {})
            cleanup_interval_s = cleanup_conf.get('interval_seconds', 30)
            service_ttl_s = cleanup_conf.get('ttl_seconds', 60)
    except FileNotFoundError:
        logger.error("Configuration file 'conf.json' not found")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading conf.json: {e}")
        sys.exit(1)
    try:
        my_db_adaptor = MongoDBAdapter(db_conf)
    except Exception as e:
        logger.error(f"Failed to initialize database connection: {e}")
        sys.exit(1)
    try:
        catalog = Catalog(my_db_adaptor, cleanup_interval_s, service_ttl_s)
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
        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing server configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)
