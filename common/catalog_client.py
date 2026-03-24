import time
import os
import subprocess
import re

import requests
import logging
import threading

logger = logging.getLogger(__name__)


def _parse_ifconfig_ipv4():
    try:
        res = subprocess.run(
            ["ifconfig"],
            check=True,
            capture_output=True,
            text=True
        )
    except Exception as exc:
        logger.debug(f"Could not run ifconfig for LAN IP detection: {exc}")
        return None

    current_iface = None
    for line in res.stdout.splitlines():
        iface_match = re.match(r"^([a-zA-Z0-9]+):", line)
        if iface_match:
            current_iface = iface_match.group(1)
            continue

        inet_match = re.match(r"^\s+inet\s+(\d+\.\d+\.\d+\.\d+)\s+", line)
        if not inet_match:
            continue

        ip = inet_match.group(1)
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        if current_iface and current_iface.startswith(("utun", "awdl", "llw", "bridge", "lo", "gif", "stf", "anpi", "ap")):
            continue
        return ip

    return None


def resolve_public_host(default="127.0.0.1"):
    env_host = (os.environ.get("PUBLIC_HOST") or "").strip()
    if env_host:
        return env_host, "PUBLIC_HOST env var"

    detected_host = _parse_ifconfig_ipv4()
    if detected_host:
        return detected_host, "auto-detected LAN IPv4"

    return default, "config fallback"


def build_public_endpoint(host, port):
    public_host, source = resolve_public_host(host)
    return f"http://{public_host}:{port}", public_host, source


class CatalogClient:
    def __init__(self, catalog_url, service_info, remove_interval=10, timeout=5, type_device=0):
        """

        Args:
            catalog_url:
            service_info:
            remove_interval:
            timeout:
            type_device: 0 for service, 1 for sensor and 2 for Actuator
        """
        self.timeout = timeout
        self._stop_event = threading.Event()
        self._worker = None
        self.catalog_url = catalog_url
        self.service_info = service_info
        self.remove_interval = remove_interval
        self.type = type_device
        self.id_key = "serviceID" if type_device == 0 else "sensorID" if type_device == 1 else "ActuatorID"

    def request(self, method, endpoint, **kwargs):
        """Make a request to the catalog.

        Returns:
            tuple: (data, status_code, error_message) — error_message is None on success.
        """
        methods = {"get": requests.get, "post": requests.post, "put": requests.put, "delete": requests.delete}
        try:
            res = methods[method.lower()](
                f"{self.catalog_url}/{endpoint}", timeout=self.timeout, **kwargs
            )
            res.raise_for_status()
            return (res.json() if res.content else {}), res.status_code, None
        except requests.exceptions.Timeout:
            logger.error(f"Catalog timeout {method} {endpoint}")
            return None, None, "Request timed out"

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            detail = e.response.json().get("error", str(e)) if e.response is not None else str(e)
            logger.error(f"Catalog HTTP error {status} {method} {endpoint}: {detail}")
            return None, status, detail

        except Exception as e:
            logger.error(f"Catalog unexpected error {method} {endpoint}: {type(e).__name__} - {e}")
            return None, None, f"Unexpected error: {e}"
    def get(self, endpoint, **kwargs):
        return self.request('get', endpoint, **kwargs)

    def post(self, endpoint, **kwargs):
        return self.request('post', endpoint, **kwargs)

    def put(self, endpoint, **kwargs):
        return self.request('put', endpoint, **kwargs)

    def delete(self, endpoint, **kwargs):
        return self.request('delete', endpoint, **kwargs)

    def register(self):
        endpoint, public_host, source = build_public_endpoint(
            self.service_info['host'],
            self.service_info['port']
        )
        service = {
            self.id_key: int(self.service_info[ self.id_key ]),
            "name": self.service_info['name'],
            "endpoint": endpoint,
            "type": self.service_info.get('type', 'generic')
        }
        logger.info(
            "Advertising service endpoint %s using host %s (%s)",
            endpoint,
            public_host,
            source
        )
        if self.type in [1, 2]:
            service["roomID"] = self.service_info.get('roomID', '')
            service["houseID"] = self.service_info.get('houseID', '')
            service["mqtt_topic"] = self.service_info.get('mqtt_topic', '')
        endpoint = "add" + ("Service" if self.type == 0 else "Sensor" if self.type == 1 else "Actuator")
        data, status, error = self.post(endpoint, json=service)
        if error:
            if status == 409:
                logger.info('Service already registered with Catalog, continuing.')
            else:
                logger.error(f'Registration failed ({status}): {error}')
                raise Exception(f'Registration failed ({status}): {error}')
        else:
            logger.info('Successfully registered with Catalog')

    def update(self):
        """Logic to update this service's info to the Catalog."""

        service = {
            self.id_key: self.service_info[self.id_key]
        }
        endpoint = "updateServiceLastUpdate" if self.type == 0 else "updateSensorLastUpdate" if self.type == 1 else "updateActuatorLastUpdate"
        data, status, error = self.put(endpoint, json=service)
        if error:
            logger.error(f'Update failed ({status}): {error}')
        else:
            logger.debug('Successfully updated with Catalog')


    def unregister(self):
        """Logic to unregister this service from the Catalog."""
        try:
            if self.type == 0:
                endpoint = f"removeService?serviceID={self.service_info['serviceID']}"
            elif self.type == 1:
                endpoint = f"removeSensor?sensorID={self.service_info['sensorID']}&&roomID={self.service_info.get('roomID','')}"
            else:
                endpoint = f"removeActuator?ActuatorID={self.service_info['ActuatorID']}&&roomID={self.service_info.get('roomID','')}"
            response = requests.delete(
                f'{self.catalog_url}/{endpoint}',
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
                logger.info("Updating Catalog with latest timestamp...")
                self.update()

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_background_loop(self):
        """Stop the background loop for periodic updates."""
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None
