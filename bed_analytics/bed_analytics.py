import json
import cherrypy
import requests


class BedAnalytics:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.register_service()

    def register_service(self):
        """Logic to send this service's info to the Catalog."""
        service = {
            "serviceID": self.service_info['serviceID'],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}"
        }
        try:
            # Note: Changed 'body' to 'json' to handle serialization automatically
            response = requests.post(f'{self.catalog_url}/addService', json=service, timeout=5)
            response.raise_for_status()
            print('Successfully registered with Catalog')
        except Exception as e:
            print(f'Registration failed: {e}')



if __name__ == "__main__":
    # Standard CherryPy startup sequence
    with open("conf.json", "r") as f:
        full_conf = json.load(f)

    # Configure the dispatcher to use GET/POST/PUT/DELETE methods
    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}

    cherrypy.tree.mount(BedAnalytics(full_conf), '/', conf)
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port']
    })

    cherrypy.engine.start()
    cherrypy.engine.block()