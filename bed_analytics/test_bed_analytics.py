import time
import json
from datetime import datetime, timedelta
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

    port = 1884
    clientID = "testPublisher"
    broker= "localhost"
    userid = "1"
    
    night_hr, night_min = 22, 0
    morning_hr, morning_min = 7, 0
    try:
        import requests
        cat_res = requests.get("http://localhost:8080/getEndpointUserService", timeout=5)
        if cat_res.status_code == 200:
            us_endpoint = cat_res.json().get("endpoint")
            if us_endpoint:
                pref_res = requests.get(f"{us_endpoint}/getUserRoomPreferences?user_id={userid}", timeout=5)
                if pref_res.status_code == 200:
                    prefs = pref_res.json().get("preferences", {})
                    n_time = prefs.get("night_time", "22:00")
                    m_time = prefs.get("morning_time", "07:00")
                    night_hr, night_min = map(int, n_time[:5].split(':'))
                    morning_hr, morning_min = map(int, m_time[:5].split(':'))
    except Exception as e:
        print(f"Failed to fetch user sleep times: {e}")

    now = datetime.now()
    yesterday_evening = (now - timedelta(days=1)).replace(hour=night_hr, minute=night_min, second=0, microsecond=0)
    today_morning = now.replace(hour=morning_hr, minute=morning_min, second=0, microsecond=0)

    Start_Sleep = int(yesterday_evening.timestamp())
    Stop_sleep = int(today_morning.timestamp())

    publisher = SimplePublisher(clientID, broker, port)
    publisher.startClient()

    start_topic = "BedAnalitics/userid/1/bedroomid/1"
    stop_topic = "BedAnalitics/userid/1/bedroomid/1"

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
