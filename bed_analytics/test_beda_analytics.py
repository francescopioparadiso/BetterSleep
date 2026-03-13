import time
import json
import paho.mqtt.client as mqtt


class SimplePublisher:

    def __init__(self, clientID, broker, port):
        self.clientID = clientID
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(clientID)

    def startClient(self):
        self.client.connect(self.broker, self.port)
        self.client.loop_start()

    def stopClient(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic, message):
        payload = json.dumps(message)
        self.client.publish(topic, payload)
        print(f"Published to {topic}: {payload}")


if __name__ == "__main__":

    Start_Sleep = 1773176400
    Stop_sleep = 1773205200

    broker = "localhost"
    port = 1883
    clientID = "testPublisher"

    publisher = SimplePublisher(clientID, broker, port)
    publisher.startClient()

    start_topic = "BedAnalitics/userid/1/Bedroom/1/StartSleep"
    stop_topic = "BedAnalitics/userid/1/Bedroom/1/FinishSleep"

    publisher.publish(
        start_topic,
        {"action": "START_SLEEP", "timestamp": Start_Sleep}
    )

    publisher.publish(
        stop_topic,
        {"action": "FINISH_SLEEP", "timestamp": Stop_sleep}
    )

    time.sleep(2)

    publisher.stopClient()