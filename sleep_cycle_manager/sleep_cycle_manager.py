import json
import sys
import time
import threading
import logging
from datetime import datetime

import cherrypy
import requests
from requests import HTTPError, Timeout, ConnectionError

# Configure logging
logger = logging.getLogger(__name__)


class SleepCycleManager:
  exposed = True

  def __init__(self, conf):
    self.catalog_url = conf['catalogURL']
    self.service_info = conf['serviceInfo']
    self.remove_interval = conf.get('removeInterval', 10)
    self._stop_event = threading.Event()
    self._worker = None
    self.register_service()

  def register_service(self):
    """Logic to send this service's info to the Catalog."""
    service = {
      "serviceID": self.service_info['serviceID'],
      "name": self.service_info['name'],
      "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
      "type": self.service_info.get('type', 'SleepCycleManager'),
      "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
      response = requests.post(f'{self.catalog_url}/addService', json=service, timeout=5)
      response.raise_for_status()
      logger.info('Successfully registered with Catalog')
    except Timeout:
      logger.error("Timeout registering service with Catalog")
    except HTTPError as e:
      logger.error(f"HTTP error during registration: {e}")
      if e.response is not None:
        logger.error(f"Status code: {e.response.status_code}, Message: {e.response.text}")
    except ConnectionError as e:
      logger.error(f"Connection error with Catalog during registration: {e}")
    except Exception as e:
      logger.error(f'Registration failed: {e}')

  def update_service(self):
    """Logic to update this service's info to the Catalog."""
    service = {
      "serviceID": self.service_info['serviceID'],
      "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
      response = requests.put(f'{self.catalog_url}/updateServiceLastUpdate', json=service, timeout=5)
      response.raise_for_status()
      logger.debug('Successfully updated with Catalog')
    except Timeout:
      logger.warning("Timeout updating service with Catalog")
    except HTTPError as e:
      logger.error(f"HTTP error during update: {e}")
      if e.response is not None:
        logger.error(f"Status code: {e.response.status_code}, Message: {e.response.text}")
    except ConnectionError as e:
      logger.error(f"Connection error with Catalog during update: {e}")
    except Exception as e:
      logger.error(f'Update failed: {e}')

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
    except Timeout:
      logger.error("Timeout unregistering service from Catalog")
    except HTTPError as e:
      logger.error(f"HTTP error during unregistration: {e}")
      if e.response is not None:
        logger.error(f"Status code: {e.response.status_code}, Message: {e.response.text}")
    except ConnectionError as e:
      logger.error(f"Connection error with Catalog during unregistration: {e}")
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
    sleep_cycle_manager = SleepCycleManager(full_conf)
    cherrypy.tree.mount(sleep_cycle_manager, '/', conf)
    cherrypy.config.update({
      'server.socket_host': full_conf['serviceInfo']['host'],
      'server.socket_port': full_conf['serviceInfo']['port']
    })

    cherrypy.engine.subscribe('start', sleep_cycle_manager.start_background_loop)
    cherrypy.engine.subscribe('stop', sleep_cycle_manager.stop_background_loop)
    cherrypy.engine.subscribe('stop', sleep_cycle_manager.unregister_service)

    cherrypy.engine.start()
    cherrypy.engine.block()
  except KeyError as e:
    logger.error(f"Missing configuration key: {e}")
    sys.exit(1)
  except Exception as e:
    logger.error(f"Error starting service: {e}")
    sys.exit(1)
