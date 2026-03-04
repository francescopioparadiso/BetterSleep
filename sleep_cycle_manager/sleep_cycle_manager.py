import json
import sys
import time
import threading
import logging
from datetime import datetime
import cherrypy
from common.catalog_client import CatalogClient

logger = logging.getLogger(__name__)

class SleepCycleManager:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self._stop_event = threading.Event()
        self._worker = None
        self.catalog_client = CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        self.catalog_client.register()



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

    cherrypy.engine.subscribe('start', sleep_cycle_manager.catalog_client.start_background_loop)
    cherrypy.engine.subscribe('stop', sleep_cycle_manager.catalog_client.stop_background_loop)
    cherrypy.engine.subscribe('stop', sleep_cycle_manager.catalog_client.unregister)

    cherrypy.engine.start()
    cherrypy.engine.block()
  except KeyError as e:
    logger.error(f"Missing configuration key: {e}")
    sys.exit(1)
  except Exception as e:
    logger.error(f"Error starting service: {e}")
    sys.exit(1)
