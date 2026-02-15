import json
import time
import threading
from datetime import datetime

import cherrypy
import requests
from requests import HTTPError


class TelegramBot:
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
    """Logic to update this service's info to the Catalog."""
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
    """Logic to unregister this service from the Catalog."""
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
      print(f'Unregister failed: {e}')

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
  with open("conf.json", "r") as f:
    full_conf = json.load(f)

  # Configure the dispatcher to use GET/POST/PUT/DELETE methods
  conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}

  telegram_bot = TelegramBot(full_conf)
  cherrypy.tree.mount(telegram_bot, '/', conf)
  cherrypy.config.update({
    'server.socket_host': full_conf['serviceInfo']['host'],
    'server.socket_port': full_conf['serviceInfo']['port']
  })

  cherrypy.engine.subscribe('start', telegram_bot.start_background_loop)
  cherrypy.engine.subscribe('stop', telegram_bot.stop_background_loop)
  cherrypy.engine.subscribe('stop', telegram_bot.unregister_service)

  cherrypy.engine.start()
  cherrypy.engine.block()
