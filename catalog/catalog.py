import json
import sys
import cherrypy
import threading
import time
from postgres_db import PostgresDB


# ============================================================
# VALIDATION FUNCTIONS
# ============================================================

def check_if_is_a_service(new_service):
    """Validate that the service contains all required fields."""
    required_fields = ['serviceID','name','type','endpoint']
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
                print("Running cleanup loop...")
                deleted = self.db.delete_stale_services(self.service_ttl_s)
                if deleted > 0:
                    print(f"Removed {deleted} stale services (ttl={self.service_ttl_s}s)")
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
        except json.JSONDecodeError:
            raise cherrypy.HTTPError(400, "Invalid JSON format")



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
        new_service = self._load_json_body()
        check_if_is_a_service(new_service)

        success = self.db.insert_service(new_service)
        if success:
            return json.dumps({"status": "success", "message": "Service Added"})
        raise cherrypy.HTTPError(409, "The Service ID already exists")

    def _post_add_device(self):
        new_device = self._load_json_body()
        check_if_is_a_device(new_device)

        success = self.db.insert_device(new_device)
        if success:
            return json.dumps({"status": "success", "message": "Device Added"})
        raise cherrypy.HTTPError(409, "The Device ID already exists")

    def _post_add_user(self):
        new_user = self._load_json_body()
        require_fields(new_user, ['username', 'telegram_chat_id', 'bedroom_id'])
        if self.db.room_exists(new_user['bedroom_id']) is False:
            raise cherrypy.HTTPError(400, "The specified bedroom_id does not exist")

        success = self.db.insert_user(new_user)
        if success:
            return json.dumps({"status": "success", "message": "User Added"})
        raise cherrypy.HTTPError(409, "The User ID already exists")

    def _post_add_bedroom(self):
        new_bedroom = self._load_json_body()
        require_fields(new_bedroom, ['room_name', 'password'])

        beed_room_id = self.db.insert_bedroom(new_bedroom)
        if beed_room_id:
            return json.dumps({"status": "success", "message": "Bedroom Added", "bedroom_id": beed_room_id})
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
            "updateUser": self._put_update_user,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _put_update_service(self):
        updated_service = self._load_json_body()
        check_if_is_a_service(updated_service)

        success = self.db.update_service(updated_service)
        if success:
            return json.dumps({"status": "success", "message": "Service updated"})
        print(f"Update failed for serviceID {updated_service.get('serviceID')}")
        raise cherrypy.HTTPError(404, "The Service ID does not exist")

    def _put_update_service_last_update(self):
        updated_service = self._load_json_body()
        require_fields(updated_service, ['serviceID', 'last_update'])

        success = self.db.update_service_last_update(updated_service['serviceID'], updated_service['last_update'])
        if success:
            return json.dumps({"status": "success", "message": "Service last_update updated"})
        print(f"Update failed for serviceID {updated_service.get('serviceID')}")
        raise cherrypy.HTTPError(404, "The Service ID does not exist")

    def _put_update_device(self):
        updated_device = self._load_json_body()
        check_if_is_a_device(updated_device)

        success = self.db.update_device(updated_device)
        if success:
            return json.dumps({"status": "success", "message": "Device updated"})
        raise cherrypy.HTTPError(404, "The Device ID does not exist")

    def _put_update_user(self):
        updated_user = self._load_json_body()
        require_fields(updated_user, ['username', 'telegram_chat_id'])

        success = self.db.update_user(updated_user)
        if success:
            return json.dumps({"status": "success", "message": "User updated"})
        raise cherrypy.HTTPError(404, "The User ID does not exist")

    # --------------------------------------------------------
    # DELETE METHOD - Remove resources
    # --------------------------------------------------------
    def DELETE(self, *uri, **params):
        """Handle DELETE requests to remove Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "removeService": self._delete_remove_service,
            "removeDevice": self._delete_remove_device,
            "removeUser": self._delete_remove_user,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler(params)

    def _delete_remove_service(self, params):
        service_id = params.get('serviceID')
        if not service_id:
            raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")

        success = self.db.delete_service(service_id)
        if success:
            return json.dumps({"status": "success", "message": "Service Deleted"})
        raise cherrypy.HTTPError(404, "Service not found")

    def _delete_remove_device(self, params):
        device_id = params.get('deviceID')
        if not device_id:
            raise cherrypy.HTTPError(400, "Missing 'deviceID' parameter")

        success = self.db.delete_device(device_id)
        if success:
            return json.dumps({"status": "success", "message": "Device Deleted"})
        raise cherrypy.HTTPError(404, "Device not found")

    def _delete_remove_user(self, params):
        username = params.get('username')
        if not username:
            raise cherrypy.HTTPError(400, "Missing 'username' parameter")

        success = self.db.delete_user(username)
        if success:
            return json.dumps({"status": "success", "message": "User Deleted"})
        raise cherrypy.HTTPError(404, "User not found")

    def _get_database_endpoint(self):
        try:
            endpoint = self.db.get_endpoint_server_database()
            if endpoint:
                return json.dumps({"status": "success", "endpoint": endpoint})
            raise cherrypy.HTTPError(404, "Database endpoint not found")
        except Exception as e:
            print(f"Error retrieving database endpoint: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_check_room(self, params):
        bedroom_id = params.get('bedroom_id')
        password = params.get('password')
        if not bedroom_id or not password:
            raise cherrypy.HTTPError(400, "Missing 'bedroom_id' or 'password' parameter")
        try:
            can_join = self.db.check_join_bedroom(bedroom_id, password)
            print(can_join)
            if not can_join:
                raise cherrypy.HTTPError(404, "Bedroom not found")
            return json.dumps({"status": "success", "can_join": can_join})
        except Exception as e:
            print(f"Error checking join bedroom: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_check_username(self, params):
        username = params.get('username')
        if not username:
            raise cherrypy.HTTPError(400, "Missing 'username' parameter")
        try:
            exists = self.db.check_user_exists(username)
            print(exists)
            return json.dumps({"status": "success", "exists": exists})
        except Exception as e:
            print(f"Error checking username: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def _get_usersession_from_chat_id(self, params):
        telegram_chat_id = params.get('telegram_chat_id')
        if not telegram_chat_id:
            raise cherrypy.HTTPError(400, "Missing 'telegram_chat_id' parameter")
        try:
            usersession=self.db.getUserSession(telegram_chat_id)
            if usersession:
                return json.dumps({"status": "success", "username": usersession[0], "bedroom_id": usersession[1]})
            raise cherrypy.HTTPError(404, "User session not found")
        except Exception as e:
            print(f"Error retrieving user session: {e}")
            raise cherrypy.HTTPError(500, "Internal Server Error")

    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "getDatabaseEndpoint": self._get_database_endpoint,
            "checkRoom": self._get_check_room,
            "checkUsername": self._get_check_username,
            "getUserSession": self._get_usersession_from_chat_id,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        if uri[0] == "getDatabaseEndpoint":
            return handler()
        return handler(params)

def json_error_page(status, message, traceback, version):
    """Override CherryPy HTTPError to return JSON instead of HTML."""
    cherrypy.response.headers["Content-Type"] = "application/json"

    # Status arriva come "404 Not Found" → prendiamo solo il numero
    try:
        status_code = int(status.split(" ")[0])
    except Exception:
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
    except Exception as e:
        print(f"Error reading conf.json: {e}")
        sys.exit(1)

    # Initialize the Database Adaptor
    my_db_adaptor = PostgresDB(db_conf)

    # Mount the Catalog REST Service
    catalog = Catalog(my_db_adaptor, cleanup_interval_s, service_ttl_s)
    cherrypy.tree.mount(catalog, '/', conf)

    # Configure Server Settings
    cherrypy.config.update({
        'server.socket_port': server_conf['port'],
        'server.socket_host': server_conf['host'],
        'error_page.default': json_error_page

    })


    # Start the Web Server
    print(f"Starting Catalog Service on {server_conf['host']}:{server_conf['port']}")
    cherrypy.engine.subscribe('start', catalog.start_cleanup_loop)
    cherrypy.engine.subscribe('stop', catalog.stop_cleanup_loop)
    cherrypy.engine.start()
    cherrypy.engine.block()
