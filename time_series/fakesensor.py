from common.MQTT.MyMQTT import MyMQTT


class simplePublisher:
    def __init__(self, clientID, broker, port, topic_publish):
        self.clientID = clientID
        self.broker = broker
        self.port = port
        self.topic_publish = topic_publish
        self.mqtt_client_publisher = MyMQTT(self.clientID, self.broker, self.port, None)

    def startClient(self):
        self.mqtt_client_publisher.start()

    def stopClient(self):
        self.mqtt_client_publisher.stop()

    def publish(self, message):
        self.mqtt_client_publisher.myPublish(self.topic_publish, message)
        print("Message Published ")


if __name__ == "__main__":
    broker = 'broker.hivemq.com'
    port = 1883
    clientID = 'SensorFakePublisher20251113'
    topic = 'House/1/Bedroom/1/sensor/temperature/1/data'
    mqtt_client_publisher = simplePublisher(clientID, broker, port, topic)
    mqtt_client_publisher.startClient()
    while True:
        # generate a fake sensor reading between 0 and 100 using sSenML

        import random
        import time
        message_to_publish = {
            #bn roomid:bedroomid:sensorid
            "bn": "1:1:2",
            "e": [
                {
                    "n": "temperature",
                    "u": "°C",
                    "t": time.time(),
                    "v": random.uniform(0, 100)
                }
            ]
        }

        time.sleep(2)
        mqtt_client_publisher.publish(message_to_publish)

    mqtt_client_publisher.stopClient()