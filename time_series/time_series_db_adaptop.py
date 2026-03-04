import json
import logging
import sys

import cherrypy

from common import catalog_client
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


class TimeSeriesDBAdapter:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog = catalog_client.CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)

        try:
            self.db = TimeSeriesDB(conf)
            self.catalog.register()
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
        """Handle POST requests to add new Services, Devices, or Users."""
        if not uri:
            raise cherrypy.HTTPError(400, "Endpoint not specified")

        handlers = {
            "addMeasurement": self._post_add_measurement,
        }
        handler = handlers.get(uri[0])
        if not handler:
            raise cherrypy.HTTPError(404, "Endpoint not found")
        return handler()

    def _post_add_measurement(self):
        newmeasurament = _load_json_body()
        # newmesurament is in senML
        checkSenML(newmeasurament)
        success = self.db.insert_data("mesurament",newmeasurament)
        if success:
            return json.dumps({"status": "success", "message": "Mesurament Added"})
        raise cherrypy.HTTPError(409, "Problem with the addition of Mesurament")

    def GET(self, *uri, **params):
        pass

    def PUT(self, *uri, **params):
        pass
    def DELETE(self, *uri, **params):
        pass



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
        cherrypy.engine.subscribe('stop', time_series_db_adapter.catalog.unregister)

        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)
