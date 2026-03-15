import sys
import math
import threading
import logging
from datetime import datetime
import cherrypy
import os
import sys
import re
from collections import defaultdict
import json
import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from common.common import json_error_page, mqtt_to_regex

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  SLEEP ANALYTICS ENGINE
# ─────────────────────────────────────────────

IDEAL_TEMP      = 20.0   # °C  — comfortable sleep temperature
VIBRATION_LIMIT = 0.01   # g   — movements above this = restless
#  HR thresholds are computed dynamically from each user's own resting HR
#  so these constants are no longer needed here


# Sensor type map — last number in bn (e.g. "2:2:32:2" → type 2 → "presence")
SENSOR_TYPE = {
    0: "temperature",
    1: "humidity",
    2: "presence",
    3: "heart_rate",
    4: "vibration",
}


def compute_hrv(hr_list):
    """
    Compute HRV as RMSSD (Root Mean Square of Successive Differences)
    from a list of heart-rate SenML entries [{"t": ..., "v": bpm}, ...].

    Steps:
        1. Convert each HR (bpm) → RR interval (ms):  RR = 60 000 / HR
        2. Compute successive differences of RR intervals.
        3. Return RMSSD = sqrt(mean(diff²)).

    Returns None if there are fewer than 2 readings.
    """
    if len(hr_list) < 2:
        return None

    # Sort by timestamp so successive differences are meaningful
    sorted_hr = sorted(hr_list, key=lambda m: m["t"])

    # HR (bpm) → RR interval (ms)
    rr_intervals = [60_000.0 / m["v"] for m in sorted_hr if m["v"] > 0]

    if len(rr_intervals) < 2:
        return None

    # Successive differences squared
    sq_diffs = [
        (rr_intervals[i + 1] - rr_intervals[i]) ** 2
        for i in range(len(rr_intervals) - 1)
    ]

    rmssd = math.sqrt(sum(sq_diffs) / len(sq_diffs))
    return round(rmssd, 1)


def parse_sensor_data(raw_data):
    sensors = {}

    for entry in raw_data:
        bn = entry.get("bn", "")

        try:
            sensor_type_id = int(bn.split(":")[-1])
            sensor_name = SENSOR_TYPE.get(sensor_type_id)
        except:
            continue

        if sensor_name:
            sensors[sensor_name] = entry.get("e", [])

    return sensors

def classify_minute(presence, vibration, heart_rate, rhr, rem_threshold):
    """
    Decide the sleep stage for one reading using simple if/else rules.

    presence      : 1 = person is in bed, anything else = not in bed
    vibration     : movement value in g
    heart_rate    : bpm reading
    rhr           : resting heart rate = lowest HR of the night
    rem_threshold : HR above this = REM  (= rhr + 75th-percentile offset)
    """
    # Not in bed → AWAKE
    if presence != 1:
        return "AWAKE"

    # Moving around → AWAKE
    if abs(vibration) > VIBRATION_LIMIT:
        return "AWAKE"

    # Still + HR close to personal resting HR → DEEP sleep
    if heart_rate <= rhr + 5:
        return "DEEP"

    # Still + elevated HR (above personal REM threshold) → REM
    if heart_rate >= rem_threshold:
        return "REM"

    # Everything else → LIGHT sleep
    return "LIGHT"


def compute_sleep_analytics(raw_data) :
    """
    Compute sleep analytics from raw sensor data in SenML format (list of dicts).
    """
    if not raw_data:
        return {"error": "No sensor data available"}

    sensors = parse_sensor_data(raw_data)

    vibration_list = sensors.get("vibration", [])
    presence_list  = sensors.get("presence", [])
    hr_list        = sensors.get("heart_rate", [])
    temp_list      = sensors.get("temperature", [])

    if not hr_list:
        return {"error": "No Heart Rate data found"}
    if not presence_list:
        return {"error": "No Presence data found — cannot determine time in bed"}

    # ── Personal HR baselines ─────────────────────────────
    hr_values = [m["v"] for m in hr_list]
    rhr = min(hr_values)                        # resting HR
    hr_sorted = sorted(hr_values)
    p75_hr = hr_sorted[int(len(hr_sorted) * 0.75)]
    rem_threshold = rhr + (p75_hr - rhr) * 0.6

    logger.info(f"HR baselines → RHR: {rhr:.1f} bpm | REM threshold: {rem_threshold:.1f} bpm")

    # ── Helper: find closest value by timestamp ──────────
    def closest_value(data_list, target_time, default):
        if not data_list:
            return default
        return min(data_list, key=lambda m: abs(m["t"] - target_time))["v"]

    # ── Classify each presence reading ─────────────────────
    classified = []
    for m in presence_list:
        t = m["t"]
        presence = m["v"]

        hr_value = closest_value(hr_list, t, default=rhr)
        vibration_value = closest_value(vibration_list, t, default=0.0)
        stage = classify_minute(presence, vibration_value, hr_value, rhr, rem_threshold)

        classified.append({
            "timestamp": t,
            "stage": stage,
            "hr": round(hr_value, 1),
            "vibration": vibration_value,
            "presence": presence
        })

    # ── Count readings per stage ──────────────────────────
    total = len(classified)
    counts = {"AWAKE": 0, "LIGHT": 0, "DEEP": 0, "REM": 0}
    for r in classified:
        counts[r["stage"]] += 1
    pct = {stage: round(counts[stage] / total * 100, 1) for stage in counts}

    # ── Sleep duration ───────────────────────────────────
    sleep_minutes = counts["LIGHT"] + counts["DEEP"] + counts["REM"]
    sleep_hours = round(sleep_minutes / 60, 1)

    # ── Wake-ups ────────────────────────────────────────
    first_sleep_idx = next((i for i, r in enumerate(classified) if r["stage"] != "AWAKE"), None)
    wake_ups = 0
    if first_sleep_idx is not None:
        for i in range(first_sleep_idx + 1, len(classified)):
            prev = classified[i - 1]["stage"]
            curr = classified[i]["stage"]
            if curr == "AWAKE" and prev != "AWAKE":
                wake_ups += 1

    # ── Sleep score (0–100) ─────────────────────────────
    score = 100.0
    if sleep_hours < 7:
        score -= (7 - sleep_hours) * 10
    if wake_ups > 2:
        score -= (wake_ups - 2) * 5
    if pct["DEEP"] < 15:
        score -= (15 - pct["DEEP"]) * 0.5
    if pct["REM"] < 20:
        score -= (20 - pct["REM"]) * 0.3

    # ── Temperature penalty ─────────────────────────────
    if temp_list:
        avg_temp = sum(m["v"] for m in temp_list) / len(temp_list)
        temp_diff = abs(avg_temp - IDEAL_TEMP)
        if temp_diff > 2:
            score -= (temp_diff - 2) * 3
    else:
        avg_temp = None

    # ── HRV (RMSSD) ────────────────────────────────────
    hrv_rmssd = compute_hrv(hr_list)

    score = round(max(0.0, min(100.0, score)), 1)

    # ── Quality label ───────────────────────────────────
    if score >= 85:
        quality = "Excellent"
    elif score >= 70:
        quality = "Good"
    elif score >= 55:
        quality = "Fair"
    else:
        quality = "Poor"

    return {
        "sleep_score":   score,
        "quality":       quality,
        "sleep_hours":   sleep_hours,
        "wake_ups":      wake_ups,
        "resting_hr":    round(rhr, 1),
        "hrv_rmssd_ms":  hrv_rmssd,
        "stage_percent": pct,
        "stage_minutes": {s: round(counts[s], 1) for s in counts},
        "avg_temp_degC": round(avg_temp, 1) if avg_temp is not None else None,
    }

# ─────────────────────────────────────────────
#  ORIGINAL BedAnalytics CLASS (extended)
# ─────────────────────────────────────────────

class BedAnalytics:
    exposed = True

    def __init__(self, conf):
        self.logger = logger
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self._stop_event = threading.Event()
        self._worker = None
        self.actualTime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.catalog_client = CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        self.catalog_client.register()
        self.timeseries_endpoint = self.get_endpoint_timeseries()
        self.mqtt_client = None
        self.MQTT_info = conf['MQTT']
        self.topic_subscribe_raw = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]
        self.cache_sleep_time = {}   # {userid: {"start": datetime, "end": datetime}}

    def get_endpoint_timeseries(self):
        data, status, error = self.catalog_client.get(f"getEndpointTimeSeries")
        if status == 200 and data:
            endpoint = data.get("endpoint")
            if endpoint:
                self.logger.info(f"Timeseries endpoint retrieved: {endpoint}")
                return endpoint
            else:
                self.logger.error("Timeseries endpoint not found in Catalog response")
                return None
        else:
            self.logger.error(f"Error retrieving Timeseries endpoint: {status} - {error}")
            return None

    def init_mqtt_client(self):
        client_id = self.MQTT_info['clientID']
        broker    = self.MQTT_info['broker']
        port      = self.MQTT_info['port']
        try:
            self.mqtt_client = MyMQTT(client_id, broker, port, self)
            self.startClient()
            for topic in self.topic_subscribe_raw:
                self.mqtt_client.mySubscribe(topic)
            logger.info(f"MQTT client initialized and subscribed to {self.topic_subscribe_raw}")
        except Exception as e:
            logger.error(f"Error initializing MQTT client: {e}")
            self.catalog_client.unregister()
            sys.exit(1)

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def _process_finish_sleep(self, userid, bedroomid, timestamp):
        logger.info(f"Recorded FINISH_SLEEP for user {userid} at {timestamp}")
        report = self.startAnalytics(self.cache_sleep_time[userid], bedroomid, userid)
        if report:
            report['user_id'] = userid
            try:
                dt = datetime.fromtimestamp(timestamp)
                report['date'] = dt.strftime("%Y-%m-%d")
            except Exception as e:
                logger.error(f"Error parsing timestamp {timestamp}: {e}")
                report['date'] = datetime.now().strftime("%Y-%m-%d")
            
            topic = f"BedAnalitics/userid/{userid}/SleepReport"
            self.mqtt_client.myPublish(topic, report)
            logger.info(f"Published analytics report for user {userid} to topic {topic}")
        else:
            logger.error(f"Analytics failed for user {userid} - no report generated")

    def notify(self, topic, payload):
        if not "SleepReport" in topic:
            try:
                message_received = json.loads(payload)
                action    = message_received.get("action")
                userid    = topic.split("/")[2]
                bedroomid = topic.split("/")[4]
                timestamp = message_received.get("timestamp")

                if action == "START_SLEEP":
                    self.cache_sleep_time[userid] = {"start": timestamp, "end": None}
                    logger.info(f"Recorded START_SLEEP for user {userid} at {timestamp}")

                elif action == "FINISH_SLEEP":
                    if userid in self.cache_sleep_time and self.cache_sleep_time[userid]["start"] is not None:
                        self.cache_sleep_time[userid]["end"] = timestamp
                        threading.Thread(target=self._process_finish_sleep, args=(userid, bedroomid, timestamp)).start()
                    else:
                        logger.warning(
                            f"Received FINISH_SLEEP for user {userid} without a corresponding START_SLEEP"
                        )
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON payload received on topic {topic}")
            except Exception as e:
                logger.error(f"Error processing payload on topic {topic}: {e}")

    def get_data_from_timeseries(self, bedroomid, start_time, end_time):
        logger.info(f"Retrieving data for bedroom {bedroomid} from {start_time} to {end_time}")
        res = requests.get(
            f"{self.timeseries_endpoint}/getSensorDataByRoomAndTimeRange"
            f"?room_id={bedroomid}&start_time={start_time}&end_time={end_time}"
        )
        if res.status_code == 200:
            logger.info(f"Data retrieved successfully for bedroom {bedroomid}")
            return res.json()
        else:
            logger.error(
                f"Failed to retrieve data for bedroom {bedroomid}: {res.status_code} - {res.text}"
            )
            return None

    def startAnalytics(self, sleep_time: dict, bedroomid: str, userid: str = None):
        """
        Fetch sensor data for the sleep window, run the analytics engine,
        store the result and log a summary.
        """
        start_time = sleep_time.get("start")
        end_time   = sleep_time.get("end")

        if not (start_time and end_time):
            logger.warning("Cannot start analytics: missing start or end time for sleep period")
            return None

        logger.info(f"Starting analytics for sleep period: {start_time} to {end_time}")
        raw_data = self.get_data_from_timeseries(bedroomid, start_time, end_time)

        if not raw_data:
            logger.warning(f"No data available for analytics for bedroom {bedroomid}")
            return None

        # ── Run the analytics engine ──────────────────────────────────────────
        report = compute_sleep_analytics(raw_data)

        if "error" in report:
            logger.error(f"Analytics error for bedroom {bedroomid}: {report['error']}")
            return None

        # ── Persist result in memory ──────────────────────────────────────────

        logger.info(f"Analytics result for user {userid} → Sleep Score: {report['sleep_score']} | "
                    f"Quality: {report['quality']} | Sleep Hours: {report['sleep_hours']} | "
                    f"Wake-ups: {report['wake_ups']} | Resting HR: {report['resting_hr']} bpm | "
                    f"HRV (RMSSD): {report['hrv_rmssd_ms']} ms | Stage %: {report['stage_percent']} | Avg Temp: {report['avg_temp_degC']}°C")
        return report




# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
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

    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}

    try:
        bed_analytics = BedAnalytics(full_conf)
        bed_analytics.init_mqtt_client()
        cherrypy.tree.mount(bed_analytics, '/', conf)
        cherrypy.config.update({
            'server.socket_host':  full_conf['serviceInfo']['host'],
            'server.socket_port':  full_conf['serviceInfo']['port'],
            'error_page.default':  json_error_page,
        })
        cherrypy.engine.subscribe('start', bed_analytics.catalog_client.start_background_loop)
        cherrypy.engine.subscribe('stop',  bed_analytics.catalog_client.stop_background_loop)
        cherrypy.engine.subscribe('stop',  bed_analytics.catalog_client.unregister)

        cherrypy.engine.start()
        cherrypy.engine.block()
    except KeyError as e:
        logger.error(f"Missing configuration key: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        sys.exit(1)