import json
import cherrypy
import sys

from catalog.postgres_db import PostgresDB

# --- CLASS 2: REST SERVICE (Handles HTTP) ---
def checkifisaService(new_service):
    required_fields = ['serviceID', 'REST_endpoint', 'MQTT_topic', 'timestamp']
    if not all(field in new_service for field in required_fields):
        raise cherrypy.HTTPError(400, "Missing required fields in JSON")


class Catalog:
    exposed = True

    def __init__(self, db_adaptor):
        self.db = db_adaptor  # Dependency Injection: The Catalog uses the DB class

    def POST(self, *uri, **params):
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")
        # Endpoint: /addService
        if uri[0] == "addService":
            body = cherrypy.request.body.read()
            try:
                new_service = json.loads(body)
                checkifisaService(new_service)
                # Insert into DB
                success = self.db.insert_service(new_service)
                if success:
                    return json.dumps({"status": "success", "message": "Service Added"})
                else:
                    raise cherrypy.HTTPError(409, "The Service ID already exists")

            except json.JSONDecodeError:
                raise cherrypy.HTTPError(400, "Invalid JSON format")
        else:
            raise cherrypy.HTTPError(404, "Endpoint not found")

    def PUT(self, *uri, **params):
            if not uri:
                raise cherrypy.HTTPError(400, "Endpoint not specified")
            # Endpoint: /addService
            if uri[0] == "updateService":
                body = cherrypy.request.body.read()
                try:
                    new_service = json.loads(body)
                    checkifisaService(new_service)
                    # Insert into DB
                    success = self.db.update_service(new_service)
                    if success:
                        return json.dumps({"status": "success", "message": "Service updated"})
                    else:
                        raise cherrypy.HTTPError(409, "The Service ID not exists")

                except json.JSONDecodeError:
                    raise cherrypy.HTTPError(400, "Invalid JSON format")
            else:
                raise cherrypy.HTTPError(404, "Endpoint not found")

    def DELETE(self, *uri, **params):
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        if uri[0] == "removeService":
            service_id = params.get('serviceID')

            if not service_id:
                raise cherrypy.HTTPError(400, "Missing 'serviceID' parameter")

            result = self.db.delete_service(service_id)

            if result:
                return json.dumps({"status": "success", "message": "Service Deleted"})
            else:
                raise cherrypy.HTTPError(404, "Service not found")
        else:
            raise cherrypy.HTTPError(404, "Endpoint not found")



if __name__ == "__main__":
    # CherryPy Standard Config
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
    except Exception as e:
        print(f"Error reading conf.json: {e}")
        sys.exit(1)

    # Initialize the Database Class
    my_db_adaptor = PostgresDB(db_conf)

    # Start the Web Server
    cherrypy.tree.mount(Catalog(my_db_adaptor), '/', conf)

    cherrypy.config.update({
        'server.socket_port': server_conf['port'],
        'server.socket_host': server_conf['host']
    })

    cherrypy.engine.start()
    cherrypy.engine.block()
