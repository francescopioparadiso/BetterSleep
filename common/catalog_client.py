import time
from datetime import datetime

import requests
import logging
import threading

logger = logging.getLogger(__name__)


# noinspection HttpUrlsUsage
class CatalogClient:
    def __init__(self, catalog_url, service_info, remove_interval=10, timeout=5, type=0):
        """

        Args:
            catalog_url:
            service_info:
            remove_interval:
            timeout:
            type: 0 for service, 1 for sensor and 2 for Actuator
        """
        self.timeout = timeout
        self._stop_event = threading.Event()
        self._worker = None
        self.catalog_url = catalog_url
        self.service_info = service_info
        self.remove_interval = remove_interval
        self.type = type

    def request(self, method, endpoint, **kwargs):
        """Make a request to the catalog and return (data, status_code, error_message).

        Returns:
            tuple: (data_dict, status_code, error_message)
                - data_dict: Response JSON as dict, or None if error
                - status_code: HTTP status code (int), or None if timeout/connection error
                - error_message: Error message string, or None if success
        """
        try:
            call = getattr(requests, method.lower())
            res = call(f"{self.catalog_url}/{endpoint}", timeout=self.timeout, **kwargs)
            res.raise_for_status()

            # Success case
            if res.content:
                try:
                    return res.json(), res.status_code, None
                except ValueError:
                    return {}, res.status_code, None
            return {}, res.status_code, None

        except requests.exceptions.Timeout as e:
            logger.error(f"Catalog timeout {method} {endpoint}: {str(e)}")
            return None, None, "Request timed out"

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            try:
                error_detail = e.response.json().get('error', str(e)) if e.response is not None else str(e)
            except:
                error_detail = str(e)

            logger.error(f"Catalog HTTP error {status_code} {method} {endpoint}: {error_detail}")
            return None, status_code, error_detail

        except Exception as e:
            logger.error(f"Catalog unexpected error {method} {endpoint}: {type(e).__name__} - {str(e)}")
            return None, None, f"Unexpected error: {str(e)}"

    def get(self, endpoint, **kwargs):
        return self.request('get', endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        return self.request('post', endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        return self.request('put', endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        return self.request('delete', endpoint, **kwargs)

    def register(self):

        idName = 'serviceID' if self.type == 0 else 'sensorID' if self.type == 1 else 'ActuatorID'
        service = {
            idName : self.service_info[idName],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
            "type": self.service_info.get('type', 'generic'),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        endpoint = 'registerService' if self.type == 0 else 'registerSensor' if self.type == 1 else 'registerActuator'
        data, status, error = self.post(endpoint, json=service)
        if error:
            logger.error(f'Registration failed ({status}): {error}')
        else:
            logger.info('Successfully registered with Catalog')

    def update(self):
        """Logic to update this service's info to the Catalog."""
        service = {
            "serviceID": self.service_info['serviceID'],
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        endpoint = 'updateLastUpdateService' if self.type == 0 else 'updateLastUpdateSensor' if self.type == 1 else 'updateLastUpdateActuator'
        data, status, error = self.put(endpoint, json=service)
        if error:
            logger.error(f'Update failed ({status}): {error}')
        else:
            logger.debug('Successfully updated with Catalog')

    def unregister(self):
        """Logic to unregister this service from the Catalog."""
        try:
            endpoint = 'unregisterService' if self.type == 0 else 'unregisterSensor' if self.type == 1 else 'unregisterActuator'
            response = requests.delete(
                f'{self.catalog_url}/{endpoint}',
                json={"serviceID": self.service_info['serviceID']} if self.type == 0 else {"sensorID": self.service_info['sensorID']} if self.type == 1 else {"ActuatorID": self.service_info['ActuatorID']},
                timeout=5
            )
            response.raise_for_status()
            logger.info('Service unregistered from Catalog')
        except Exception as e:
            logger.error(f'Unregister failed: {e}')



    def start_background_loop(self):
        """Start the background loop for periodic updates."""
        if self._worker is not None:
            return

        def _loop():
            while not self._stop_event.is_set():
                time.sleep(self.remove_interval)
                print(f"Updating service info at {datetime.now()}...")
                self.update()

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_background_loop(self):
        """Stop the background loop for periodic updates."""
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None

