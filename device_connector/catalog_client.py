import requests
import json

class CatalogClient:
    def __init__(self, catalog_url):
        self.catalog_url = catalog_url

    def register(self, device_data, is_service=True):
        """
        Registers a component with the Catalog.
        is_service: True for microservices, False for sensors/devices.
        """
        endpoint = "/register/service" if is_service else "/register/device"
        try:
            response = requests.post(f"{self.catalog_url}{endpoint}", json=device_data)
            if response.status_code == 200:
                print(f"Successfully registered as {'Service' if is_service else 'Sensor/Device'}")
                return response.json()
            else:
                print(f"Registration failed with status: {response.status_code}")
        except Exception as e:
            print(f"Error connecting to Catalog: {e}")
        return None
