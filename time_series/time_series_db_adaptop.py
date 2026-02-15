import json
import time
import threading
from datetime import datetime

import cherrypy
import requests
from requests import HTTPError

from time_series.time_series_db import TimeSeriesDB


class TimeSeriesDBAdapter:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self._stop_event = threading.Event()
        self._worker = None
        self.db = TimeSeriesDB(conf)
        self.register_service()
        if not self.db.health_check():
            print("Critical error: Unable to connect to the database.")
            print("Service will be stopped.")
            self.stop_background_loop()


    def GET(self, *uri, **params):
        pass
    def POST(self, *uri, **params):
        pass
    def PUT(self, *uri, **params):
        pass
    def DELETE(self, *uri, **params):
        pass
    def register_service(self):
        """
        This function registers this service with the Catalog by sending a POST request to the Catalog's /addService endpoint.
        Returns:None
        """
        service = {
            "serviceID": self.service_info['serviceID'],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            response = requests.post(f'{self.catalog_url}/addService', json=service, timeout=5)
            response.raise_for_status()
            print('Successfully registered with Catalog')
        except HTTPError as e:
            print(f"HTTP error during registration: {e}")
            if e.response is not None:
                print("Status code:", e.response.status_code)
                print("Server message:", e.response.text)
        except Exception as e:
            print(f'Registration failed: {e}')

    def update_service(self):
        """
        This function updates the service information in the Catalog by sending a PUT request to the Catalog's /updateService endpoint.
        Returns: None
        """
        # Only update if the database is still connected
        if not self.db.health_check():
            print('Database connection lost, not updating service')
            return

        service = {
            "serviceID": self.service_info['serviceID'],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            response = requests.put(f'{self.catalog_url}/updateService', json=service, timeout=5)
            response.raise_for_status()
            print('Successfully updated with Catalog')
        except HTTPError as e:
            print(f"HTTP error during update: {e}")
            if e.response is not None:
                print("Status code:", e.response.status_code)
                print("Server message:", e.response.text)
        except Exception as e:
            print(f'Update failed: {e}')


    def unregister_service(self):
        """
        This function unregisters this service from the Catalog by sending a DELETE request to the Catalog's /removeService endpoint.
        Returns: None
        """
        try:
            response = requests.delete(
                f'{self.catalog_url}/removeService',
                params={'serviceID': self.service_info['serviceID']},
                timeout=5
            )
            response.raise_for_status()
            print('Service unregistered from Catalog')
        except HTTPError as e:
            print(f"HTTP error during unregistration: {e}")
            if e.response is not None:
                print("Status code:", e.response.status_code)
                print("Server message:", e.response.text)
        except Exception as e:
            print(f'Unregistration failed: {e}')

    def start_background_loop(self):
        """Start the background loop for periodic updates."""
        if self._worker is not None:
            return

        def _loop():
            while not self._stop_event.is_set():
                time.sleep(self.remove_interval)
                if not self._stop_event.is_set():
                    print(f"Updating service info at {datetime.now()}...")
                    self.update_service()

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_background_loop(self):
        """Stop the background loop for periodic updates."""
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None
        self.db.disconnect()


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
    # Standard CherryPy startup sequence
    with open("conf.json", "r") as f:
        full_conf = json.load(f)

    # Configure the dispatcher to use GET/POST/PUT/DELETE methods
    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}

    time_series_db_adapter = TimeSeriesDBAdapter(full_conf)
    cherrypy.tree.mount(time_series_db_adapter, '/', conf)
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port'],
        'error_page.default': json_error_page

    })

    cherrypy.engine.subscribe('start', time_series_db_adapter.start_background_loop)
    cherrypy.engine.subscribe('stop', time_series_db_adapter.stop_background_loop)
    cherrypy.engine.subscribe('stop', time_series_db_adapter.unregister_service)

    cherrypy.engine.start()
    cherrypy.engine.block()