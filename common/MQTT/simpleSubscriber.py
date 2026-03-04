from MyMQTT import *
import time

class simpleSubscriber:
    def __init__(self,clientID,broker,port,topic_subscribe):
        self.clientID=clientID
        self.broker=broker
        self.port=port
        self.topic_subscribe=topic_subscribe
        self.mqtt_client_subscriber=MyMQTT(self.clientID,self.broker,self.port, self)
    
    def notify(self,topic,payload):
        message_received=json.loads(payload)
        print(message_received)
    
    def startClient(self):
        self.mqtt_client_subscriber.start()
        self.mqtt_client_subscriber.mySubscribe(self.topic_subscribe)
    
    def stopClient(self):
        #self.mqtt_client_subscriber.unsubscribe() -> not necessary because stop is already unsubscribing
        self.mqtt_client_subscriber.stop()

if __name__=="__main__":
    broker='broker.hivemq.com'
    port=1883
    clientID='rafaIoTsubscriberdonotusethesame20251113'
    topic='IoT/rafa/simpletest20251113'
    mqtt_client=simpleSubscriber(clientID,broker,port,topic)
    mqtt_client.startClient()
    while True:
        time.sleep(5)
