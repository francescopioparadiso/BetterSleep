import json
import sys
import logging
import cherrypy
import threading
import time
from postgres_db import PostgresDB

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================
# VALIDATION FUNCTIONS
# ============================================================

def check_if_is_a_service(new_service):
    """Validate that the service contains all required fields."""
    required_fields = ['serviceID','name','type','endpoint','last_update']
    require_fields(new_service, required_fields)


def check_if_is_a_device(new_device):
    """Validate that the device contains all required fields."""
    required_fields = ['deviceID', 'device_name', 'measure_types', 'bedroom_id']
    require_fields(new_device, required_fields)

def require_fields(payload, required_fields):
    if not all(field in payload for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")
# ============================================================
# CATALOG REST SERVICE
# ============================================================

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
                    logger.debug("Running cleanup loop...")
                    deleted = self.db.delete_stale_services(self.service_ttl_s)
                    if deleted > 0:
                        logger.info(f"Removed {deleted} stale services (ttl={self.service_ttl_s}s)")
                except Exception as e:
                    logger.error(f"Error during cleanup loop: {e}")
                time.sleep(self.cleanup_interval_s)

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_cleanup_loop(self):
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=10)
            self._worker = None

    def _load_json_body(self):
        body = cherrypy.request.body.read()
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format in request body: {e}")
            raise cherrypy.HTTPError(400, "Invalid JSON format")
        except Exception as e:
            logger.error(f"Unexpected error parsing request body: {e}")
            raise cherrypy.HTTPError(400, "Error parsing request body")



    # --------------------------------------------------------
    # POST METHOD - Add new resources
    # --------------------------------------------------------
    def POST(self, *uri, **params):
        """Handle POST requests to add new Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "addService": self._post_add_service,
            "addDevice": self._post_add_device,
            "addUser": self._post_add_user,
            "addBedroom": self._post_add_bedroom,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _post_add_service(self):
        """Add a new service to the catalog."""
        new_service = self._load_json_body()
        check_if_is_a_service(new_service)

        success = self.db.insert_service(new_service)
        if success:
            return json.dumps({"status": "success", "message": "Service Added"})
        raise cherrypy.HTTPError(409, "The Service ID already exists")

    def _post_add_device(self):
        """Add a new device to the catalog."""
        new_device = self._load_json_body()
        check_if_is_a_device(new_device)

        success = self.db.insert_device(new_device)
        if success:
            return json.dumps({"status": "success", "message": "Device Added"})
        raise cherrypy.HTTPError(409, "The Device ID already exists")

    def _post_add_user(self):
        """Add a new user to the catalog."""
        new_user = self._load_json_body()
        require_fields(new_user, ['username', 'telegram_chat_id'])

        success = self.db.insert_user(new_user)
        if success:
            return json.dumps({"status": "success", "message": "User Added"})
        raise cherrypy.HTTPError(409, "The User ID already exists")

    def _post_add_bedroom(self):
        """Add a new bedroom to the catalog."""
        new_bedroom = self._load_json_body()
        require_fields(new_bedroom, ['room_name', 'password'])

        bedroom_id = self.db.insert_bedroom(new_bedroom)
        if bedroom_id:
            return json.dumps({"status": "success", "message": "Bedroom Added", "bedroom_id": bedroom_id})
        raise cherrypy.HTTPError(409, "Failed to create bedroom")

    # --------------------------------------------------------
    # PUT METHOD - Update existing resources
    # --------------------------------------------------------
    def PUT(self, *uri, **params):
        """Handle PUT requests to update Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "updateService": self._put_update_service,
            "updateServiceLastUpdate": self._put_update_service_last_update,
            "updateDevice": self._put_update_device,
            "associateUserToBedroom": self._put_update_user,
            "leaveBedroom": self._put_leave_bedroom,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _put_update_service(self):
        """Update an existing service in the catalog."""
        updated_service = self._load_json_body()
        check_if_is_a_service(updated_service)

        success = self.db.update_service(updated_service)
        if success:
            return json.dumps({"status": "success", "message": "Service updated"})
        logger.warning(f"Update failed for serviceID {updated_service.get('serviceID')}")
        raise cherrypy.HTTPError(404, "The Service ID does not exist")

    def _put_update_service_last_update(self):
        """Update the last_update timestamp of a service."""
        updated_service = self._load_json_body()
        require_fields(updated_service, ['serviceID', 'last_update'])

        success = self.db.update_service_last_update(updated_service['serviceID'], updated_service['last_update'])
        if success:
            return json.dumps({"status": "success", "message": "Service last_update updated"})
        logger.warning(f"Update failed for serviceID {updated_service.get('serviceID')}")
        raise cherrypy.HTTPError(404, "The Service ID does not exist")

    def _put_update_device(self):
        """Update an existing device in the catalog."""
        updated_device = self._load_json_body()
        check_if_is_a_device(updated_device)

        success = self.db.update_device(updated_device)
        if success:
            return json.dumps({"status": "success", "message": "Device updated"})
        raise cherrypy.HTTPError(404, "The Device ID does not exist")

    def _put_update_user(self):
        """Update an existing user's association with a bedroom."""
        updated_user = self._load_json_body()
        require_fields(updated_user, [ 'telegram_chat_id', 'bedroom_id'])

        success = self.db.associete_user_to_bedroom(updated_user)
        if success:
            return json.dumps({"status": "success", "message": "User updated"})
        raise cherrypy.HTTPError(404, "The User ID does not exist")
    def _put_leave_bedroom(self):
        """Update an existing user's association with a bedroom."""
        updated_user = self._load_json_body()
        require_fields(updated_user, ['telegram_chat_id'])

        success = self.db.dissociete_user_from_bedroom(updated_user)
        if success:
            return json.dumps({"status": "success", "message": "User left bedroom"})
        raise cherrypy.HTTPError(404, "The User ID does not exist")
    # --------------------------------------------------------
    # DELETE METHOD - Remove resources
    # --------------------------------------------------------
    def DELETE(self, *uri, **params):
        """Handle DELETE requests to remove Services, Devices, Users, or Bedrooms."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "removeService": self._delete_remove_service,
            "removeDevice": self._delete_remove_device,
            "removeUser": self._delete_remove_user,
            "removeRoom": self._delete_remove_room,
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

    def _delete_remove_room(self, params):
        """Delete a bedroom by bedroom_id."""
        bedroom_id = params.get('bedroom_id')
        if not bedroom_id:
            raise cherrypy.HTTPError(400, "Missing 'bedroom_id' parameter")

        success = self.db.delete_bedroom(bedroom_id)
        if success:
            return json.dumps({"status": "success", "message": "Bedroom Deleted"})
        raise cherrypy.HTTPError(404, "Bedroom not found")

    def _delete_remove_device(self, params):
        """Delete a device by deviceID."""
        device_id = params.get('deviceID')
        if not device_id:
            raise cherrypy.HTTPError(400, "Missing 'deviceID' parameter")

        success = self.db.delete_device(device_id)
        if success:
            return json.dumps({"status": "success", "message": "Device Deleted"})
        raise cherrypy.HTTPError(404, "Device not found")

    def _delete_remove_user(self, params):
        """Delete a user by username."""
        username = params.get('username')
        if not username:
            raise cherrypy.HTTPError(400, "Missing 'username' parameter")

        success = self.db.delete_user(username)
        if success:
            return json.dumps({"status": "success", "message": "User Deleted"})
        raise cherrypy.HTTPError(404, "User not found")

    # --------------------------------------------------------
    # GET METHOD - Retrieve resources
    # --------------------------------------------------------
    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, Users, or Bedrooms."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "getDatabaseEndpoint": self._get_database_endpoint,
            "checkRoom": self._get_check_room,
            "checkUsername": self._get_check_username,
            "getUserSession": self._get_user_session_from_chat_id,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _get_database_endpoint(self, params):
        """Get the endpoint of the database server."""
        try:
            endpoint = self.db.get_endpoint_server_database()
            if endpoint:
                return json.dumps({"status": "success", "endpoint": endpoint})
            logger.warning("Database endpoint not found")
            raise cherrypy.HTTPError(404, "Database endpoint not found")
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving database endpoint: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_check_room(self, params):
        """Check if a bedroom exists and password is correct."""
        bedroom_id = params.get('bedroom_id')
        password_hash = params.get('password')

        if not bedroom_id or not password_hash:
            raise cherrypy.HTTPError(400, "Missing 'bedroom_id' or 'password' parameter")
        try:
            can_join = self.db.check_join_bedroom(bedroom_id, password_hash)
            if not can_join:
                logger.warning(f"Failed bedroom access attempt for room {bedroom_id}")
                raise cherrypy.HTTPError(404, "Bedroom not found or incorrect password")
            return json.dumps({"status": "success", "can_join": can_join})
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            logger.error(f"Error checking join bedroom: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_check_username(self, params):
        """Check if a username exists in the database."""
        username = params.get('username')
        if not username:
            raise cherrypy.HTTPError(400, "Missing 'username' parameter")
        try:
            exists = self.db.check_user_exists(username)
            return json.dumps({"status": "success", "exists": exists})
        except Exception as e:
            logger.error(f"Error checking username: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_user_session_from_chat_id(self, params):
        """Retrieve user session (username and bedroom_id) by telegram_chat_id."""
        telegram_chat_id = params.get('telegram_chat_id')
        if not telegram_chat_id:
            raise cherrypy.HTTPError(400, "Missing 'telegram_chat_id' parameter")
        try:
            usersession = self.db.getUserSession(telegram_chat_id)
            if usersession:
                return json.dumps({"status": "success", "username": usersession[0], "bedroom_id": usersession[1]})
            else:
                logger.debug(f"No session found for chat_id {telegram_chat_id}")
                raise cherrypy.HTTPError(404, "User session not found")
        except cherrypy.HTTPError:
            raise
        except Exception as e:
            logger.error(f"Error retrieving user session: {e}")
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
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in 'conf.json': {e}")
        sys.exit(1)
    except KeyError as e:
        logger.error(f"Missing required configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading conf.json: {e}")
        sys.exit(1)

    # Initialize the Database Adaptor
    try:
        my_db_adaptor = PostgresDB(db_conf)
    except Exception as e:
        logger.error(f"Failed to initialize database connection: {e}")
        sys.exit(1)

    # Mount the Catalog REST Service
    try:
        catalog = Catalog(my_db_adaptor, cleanup_interval_s, service_ttl_s)
        cherrypy.tree.mount(catalog, '/', conf)

        # Configure Server Settings
        cherrypy.config.update({
            'server.socket_port': server_conf['port'],
            'server.socket_host': server_conf['host'],
            'error_page.default': json_error_page

        })

        # Start the Web Server
        logger.info(f"Starting Catalog Service on {server_conf['host']}:{server_conf['port']}")
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
