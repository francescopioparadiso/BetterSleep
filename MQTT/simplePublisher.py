from MyMQTT import *
import time

class simplePublisher:
    def __init__(self,clientID,broker,port,topic_publish):
        self.clientID=clientID
        self.broker=broker
        self.port=port
        self.topic_publish=topic_publish
        self.mqtt_client_publisher=MyMQTT(self.clientID,self.broker,self.port, None)
    
    def startClient(self):
        self.mqtt_client_publisher.start()
    
    def stopClient(self):
        self.mqtt_client_publisher.stop()
    
    def publish(self,message):
        self.mqtt_client_publisher.myPublish(self.topic_publish,message)
        print("Message Published ")

if __name__=="__main__":
    broker='broker.hivemq.com'
    port=1883
    clientID='rafaIoTsimplePublisherdonotcopy20251113'
    topic='IoT/rafa/simpletest20251113'
    mqtt_client_publisher=simplePublisher(clientID,broker,port,topic)
    mqtt_client_publisher.startClient()
    while True:
        user_input=input("Write sth: ")
        message_to_publish={"message":user_input,"timestamp":time.time()}
        mqtt_client_publisher.publish(message_to_publish)
    mqtt_client_publisher.stopClient()