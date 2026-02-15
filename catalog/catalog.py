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
    if not all(field in new_service for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")


def check_if_is_a_device(new_device):
    """Validate that the device contains all required fields."""
    required_fields = ['deviceID', 'device_name', 'measure_types', 'bedroom_id']
    if not all(field in new_device for field in required_fields):
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

    # --------------------------------------------------------
    # POST METHOD - Add new resources
    # --------------------------------------------------------
    def POST(self, *uri, **params):
        """Handle POST requests to add new Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        # Endpoint: /addService
        if uri[0] == "addService":
            body = cherrypy.request.body.read()
            try:
                new_service = json.loads(body)
                check_if_is_a_service(new_service)

                success = self.db.insert_service(new_service)
                if success:
                    return json.dumps({"status": "success", "message": "Service Added"})
                else:
                    raise cherrypy.HTTPError(409, "The Service ID already exists")

            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")

        # Endpoint: /addDevice
        elif uri[0] == 'addDevice':
            body = cherrypy.request.body.read()
            try:
                new_device = json.loads(body)
                check_if_is_a_device(new_device)

                success = self.db.insert_device(new_device)
                if success:
                    return json.dumps({"status": "success", "message": "Device Added"})
                else:
                    raise cherrypy.HTTPError(409, "The Device ID already exists")

            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")

        # Endpoint: /addUser
        elif uri[0] == 'addUser':
            body = cherrypy.request.body.read()
            try:
                new_user = json.loads(body)
                if 'username' not in new_user or 'telegram_chat_id' not in new_user or 'bedroom_id' not in new_user:
                    raise cherrypy.HTTPError(400, "Missing required fields in JSON")
                if self.db.room_exists(new_user['bedroom_id'])  is False:
                        raise cherrypy.HTTPError(400, "The specified bedroom_id does not exist")
                success = self.db.insert_user(new_user)
                if success:
                    return json.dumps({"status": "success", "message": "User Added"})
                else:
                    raise cherrypy.HTTPError(409, "The User ID already exists")

            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")
        elif uri[0] == 'addBedroom':
            body = cherrypy.request.body.read()
            try:
                new_bedroom = json.loads(body)
                if  'room_name' not in new_bedroom or 'password' not in new_bedroom:
                    raise cherrypy.HTTPError(400, "Missing required fields in JSON")
                success = self.db.insert_bedroom(new_bedroom)
                if success:
                    return json.dumps({"status": "success", "message": "Bedroom Added"})
                else:
                    raise cherrypy.HTTPError(400, "Error adding bedroom")
            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")


        else:
            raise cherrypy.HTTPError(404, "Endpoint not found")

    # --------------------------------------------------------
    # PUT METHOD - Update existing resources
    # --------------------------------------------------------
    def PUT(self, *uri, **params):
        """Handle PUT requests to update Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        # Endpoint: /updateService
        if uri[0] == "updateService":
            body = cherrypy.request.body.read()
            try:
                updated_service = json.loads(body)
                check_if_is_a_service(updated_service)

                success = self.db.update_service(updated_service)
                if success:
                    return json.dumps({"status": "success", "message": "Service updated"})
                else:
                    print(f"Update failed for serviceID {updated_service.get('serviceID')}")
                    raise cherrypy.HTTPError(404, "The Service ID does not exist")
            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")
        elif uri[0] == "updateServiceLastUpdate":
            body = cherrypy.request.body.read()
            try:
                updated_service = json.loads(body)
                if 'serviceID' not in updated_service or 'last_update' not in updated_service:
                    raise cherrypy.HTTPError(400, "Missing required fields in JSON")

                success = self.db.update_service_last_update(updated_service['serviceID'], updated_service['last_update'])
                if success:
                    return json.dumps({"status": "success", "message": "Service last_update updated"})
                else:
                    print(f"Update failed for serviceID {updated_service.get('serviceID')}")
                    raise cherrypy.HTTPError(404, "The Service ID does not exist")
            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")

        # Endpoint: /updateDevice
        elif uri[0] == 'updateDevice':
            body = cherrypy.request.body.read()
            try:
                updated_device = json.loads(body)
                check_if_is_a_device(updated_device)

                success = self.db.update_device(updated_device)
                if success:
                    return json.dumps({"status": "success", "message": "Device updated"})
                else:
                    raise cherrypy.HTTPError(404, "The Device ID does not exist")

            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")

        # Endpoint: /updateUser
        elif uri[0] == 'updateUser':
            body = cherrypy.request.body.read()
            try:
                updated_user = json.loads(body)
                if 'username' not in updated_user or 'telegram_chat_id' not in updated_user:
                    raise cherrypy.HTTPError(400, "Missing required fields in JSON")

                success = self.db.update_user(updated_user)
                if success:
                    return json.dumps({"status": "success", "message": "User updated"})
                else:
                    raise cherrypy.HTTPError(404, "The User ID does not exist")

            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")

        else:
            raise cherrypy.HTTPError(404, "Endpoint not found")

    # --------------------------------------------------------
    # DELETE METHOD - Remove resources
    # --------------------------------------------------------
    def DELETE(self, *uri, **params):
        """Handle DELETE requests to remove Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        # Endpoint: /removeService
        if uri[0] == "removeService":
            service_id = params.get('serviceID')
            if not service_id:
                raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")

            success = self.db.delete_service(service_id)
            if success:
                return json.dumps({"status": "success", "message": "Service Deleted"})
            else:
                raise cherrypy.HTTPError(404, "Service not found")

        # Endpoint: /removeDevice
        elif uri[0] == "removeDevice":
            device_id = params.get('deviceID')
            if not device_id:
                raise cherrypy.HTTPError(400, "Missing 'deviceID' parameter")

            success = self.db.delete_device(device_id)
            if success:
                return json.dumps({"status": "success", "message": "Device Deleted"})
            else:
                raise cherrypy.HTTPError(404, "Device not found")

        # Endpoint: /removeUser
        elif uri[0] == "removeUser":
            username = params.get('username')
            if not username:
                raise cherrypy.HTTPError(400, "Missing 'username' parameter")

            success = self.db.delete_user(username)
            if success:
                return json.dumps({"status": "success", "message": "User Deleted"})
            else:
                raise cherrypy.HTTPError(404, "User not found")

        else:
            raise cherrypy.HTTPError(404, "Endpoint not found")
    def GET(self, *uri, **params):
        """Handle GET requests to retrieve information about Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        # Endpoint: /getServices
        if uri[0] == "getDatabaseEndpoint":
            try:
                endpoint = self.db.get_endpoint_server_database()
                if endpoint:
                    return json.dumps({"status": "success", "endpoint": endpoint})
                else:
                    raise cherrypy.HTTPError(404, "Database endpoint not found")
            except Exception as e:
                print(f"Error retrieving database endpoint: {e}")
                raise cherrypy.HTTPError(500, "Internal Server Error")
        else:
            raise cherrypy.HTTPError(404, "Endpoint not found")

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
