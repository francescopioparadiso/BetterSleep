import json

from device_connector.models import Actuator


class Fan(Actuator):
    def __init__(self,config):
        super().__init__(config)
        self.value = 0  # Default fan speed (0-100%)

    def on_message(self, client, userdata, msg):
        if msg.topic == self.topic:
            try:
                payload = json.loads(msg.payload.decode())
                self.value = payload.get("value", 0)
                print(f"Fan '{self.name}' set to {self.value}%")
            except json.JSONDecodeError:
                print(f"Invalid JSON payload for fan '{self.name}'")





     
