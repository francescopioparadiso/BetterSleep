import time
from datetime import datetime
import requests
import logging
import threading

logger = logging.getLogger(__name__)

class CatalogClient:
    def __init__(self, catalog_url, service_info, remove_interval=10, timeout=5, type=0):
        self.timeout = timeout
        self._stop_event = threading.Event()
        self._worker = None
        self.catalog_url = catalog_url
        self.service_info = service_info
        self.remove_interval = remove_interval
        self.type = type # 0 service, 1 sensor, 2 actuator

    def request(self, method, endpoint, **kwargs):
        try:
            call = getattr(requests, method.lower())
            res = call(f"{self.catalog_url}/{endpoint}", timeout=self.timeout, **kwargs)
            res.raise_for_status()
            if res.content:
                try: return res.json(), res.status_code, None
                except ValueError: return {}, res.status_code, None
            return {}, res.status_code, None
        except Exception as e:
            return None, None, str(e)

    def post(self, endpoint, **kwargs): return self.request('post', endpoint, **kwargs)
    def put(self, endpoint, **kwargs): return self.request('put', endpoint, **kwargs)

    def register(self):
        idName = 'serviceID' if self.type == 0 else 'sensorID' if self.type == 1 else 'ActuatorID'
        service = {
            idName : self.service_info[idName],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
            "type": self.service_info.get('type', 'generic'),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        endpoint = "add"+("Service" if self.type == 0 else "Sensor" if self.type == 1 else "Actuator")
        data, status, error = self.post(endpoint, json=service)
        if not error: print(f"Successfully registered {self.service_info[idName]} with Catalog")

    def update(self):
        idName = 'serviceID' if self.type == 0 else 'sensorID' if self.type == 1 else 'ActuatorID'
        service = { idName: self.service_info[idName], "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S") }
        endpoint = "updateServiceLastUpdate" if self.type == 0 else "updateSensorLastUpdate" if self.type == 1 else "updateActuatorLastUpdate"
        self.put(endpoint, json=service)

    def start_background_loop(self):
        if self._worker is not None: return
        def _loop():
            while not self._stop_event.is_set():
                time.sleep(self.remove_interval)
                self.update()
        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()
