import time
from datetime import datetime

import requests
import logging
import threading

logger = logging.getLogger(__name__)

class CatalogClient:
    def __init__(self,catalog_url,service_info,remove_interval=10, timeout=5):
        self.timeout = timeout
        self._stop_event = threading.Event()
        self._worker = None
        self.catalog_url = catalog_url
        self.service_info = service_info
        self.remove_interval = remove_interval
    def request(self, method, endpoint, **kwargs):
        try:
            call = getattr(requests, method.lower())
            res = call(f"{self.catalog_url}/{endpoint}", timeout=self.timeout, **kwargs)
            res.raise_for_status()
            # Some endpoints may return no body (204) or non-JSON; handle gracefully
            if res.content:
                try:
                    return res.json()
                except ValueError:
                    return {}
            return {}
        except requests.exceptions.Timeout:
            logger.warning(f"Catalog timeout {method} {endpoint}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"Catalog HTTP error {method} {endpoint}: {e}")
        except Exception as e:
            logger.error(f"Catalog unexpected error {method} {endpoint}: {e}")
        return None

    def get(self, endpoint, **kwargs):
        return self.request('get', endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        return self.request('post', endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        return self.request('put', endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        return self.request('delete', endpoint, **kwargs)

    def register_service(self):
        service = {
            "serviceID": self.service_info['serviceID'],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
            "type": self.service_info.get('type', 'Analytics'),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        # Use the client wrapper so we get consistent timeout/error handling
        response = self.post('addService', json=service)
        if response is not None:
            logger.info('Successfully registered with Catalog')
        else:
            logger.error('Registration failed: request returned None')

    def update_service(self):
        """Logic to update this service's info to the Catalog."""
        service = {
            "serviceID": self.service_info['serviceID'],
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        # Use the client wrapper so we get consistent timeout/error handling
        response = self.put('updateServiceLastUpdate', json=service)
        if response is not None:
            logger.debug('Successfully updated with Catalog')
        else:
            logger.error('Update failed: request returned None')

    def unregister_service(self):
        """Logic to unregister this service from the Catalog."""
        try:
            response = requests.delete(
                f'{self.catalog_url}/removeService',
                params={'serviceID': self.service_info['serviceID']},
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
                self.update_service()

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_background_loop(self):
        """Stop the background loop for periodic updates."""
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None
