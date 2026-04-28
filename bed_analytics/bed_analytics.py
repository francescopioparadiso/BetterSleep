import math
import threading
import logging
from datetime import datetime
import cherrypy
import re
import json
import requests

from common.catalog_client import CatalogClient
from common.common import json_error_page, mqtt_to_regex, init_mqtt_helper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

SENSOR_TYPE = {
    0: "temperature",
    1: "humidity",
    2: "presence",
    3: "heart_rate",
    4: "vibration",
}


def _closest_value(data_list, target_time, default):
    if not data_list:
        return default
    return min(data_list, key=lambda m: abs(m["t"] - target_time))["v"]


def _compute_stage_stats(classified):
    total  = len(classified)
    counts = {"AWAKE": 0, "LIGHT": 0, "DEEP": 0, "REM": 0}
    for r in classified:
        counts[r["stage"]] += 1
    stage_percent = {stage: round(counts[stage] / total * 100, 1) for stage in counts}
    return counts, stage_percent


def _count_wakeups(classified):
    first_sleep_idx = next(
        (i for i, r in enumerate(classified) if r["stage"] != "AWAKE"), None
    )
    wake_ups = 0
    if first_sleep_idx is not None:
        for i in range(first_sleep_idx + 1, len(classified)):
            if classified[i]["stage"] == "AWAKE" and classified[i - 1]["stage"] != "AWAKE":
                wake_ups += 1
    counts, _ = _compute_stage_stats(classified)
    sleep_minutes = counts["LIGHT"] + counts["DEEP"] + counts["REM"]
    sleep_hours   = round(sleep_minutes / 60, 1)
    return wake_ups, sleep_hours


def _compute_hrv(hr_list):
    if len(hr_list) < 2:
        return None
    sorted_hr = sorted(hr_list, key=lambda m: m["t"])
    rr_intervals = [60_000.0 / m["v"] for m in sorted_hr if m["v"] > 0]
    if len(rr_intervals) < 2:
        return None
    sq_diffs = [
        (rr_intervals[i + 1] - rr_intervals[i]) ** 2
        for i in range(len(rr_intervals) - 1)
    ]
    rmssd = math.sqrt(sum(sq_diffs) / len(sq_diffs))
    return round(rmssd, 1)


def _compute_hr_thresholds(hr_list):
    hr_values = [m["v"] for m in hr_list]

    hr_sorted = sorted(hr_values)
    rhr = sum(hr_sorted[:5]) / 5  #calculate resting heart rate as average of 5 lowest readings
    p75_hr = hr_sorted[int(len(hr_sorted) * 0.75)] # 75th percentile of heart rate readings
    rem_threshold = rhr + (p75_hr - rhr) * 0.75
    return rhr, rem_threshold


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
        self.timeseries_endpoint = self.get_endpoint_timeseries()

        self.IDEAL_TEMP = conf.get('IDEAL_TEMP', 20.0)
        self.VIBRATION_LIMIT = conf.get('VIBRATION_LIMIT', 0.01)
        self.MIN_SLEEP_HOURS = conf.get('MIN_SLEEP_HOURS', 6.5)
        self.MAX_WAKE_UPS = conf.get('MAX_WAKE_UPS', 2)
        self.MIN_DEEP_stage_percent = conf.get('MIN_DEEP_stage_percent', 15.0)
        self.MIN_REM_stage_percent = conf.get('MIN_REM_stage_percent', 18.0)
        self.TEMP_TOLERANCE = conf.get('TEMP_TOLERANCE', 2.0)

        self.catalog_client.register()

        self.mqtt_client = None
        self.MQTT_info = conf['MQTT']
        self.topic_subscribe_raw = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]
        self.cache_sleep_time = {}   # {userid: {"start": datetime, "end": datetime}}

    def get_endpoint_timeseries(self):
        data, status, error = self.catalog_client.get("catalog/services/time_series?scope=internal")
        if status == 200 and data:
            endpoint = data.get("endpoint")
            if endpoint:
                self.logger.info(f"Timeseries endpoint retrieved: {endpoint}")
                return endpoint
            else:
                self.logger.error("Timeseries endpoint not found in Catalog response")
                return None
        else:
            self.logger.error(
                f"Failed to retrieve timeseries endpoint from Catalog: {status} - {error} Stopping service."
            )
            raise SystemExit(1)

    def init_mqtt_client(self):
        try:
            self.mqtt_client = init_mqtt_helper(self, self.MQTT_info, logger)
            if self.mqtt_client is None:
                self.catalog_client.unregister()
                raise SystemExit(1)
        except Exception as e:
            logger.error(f"Error initializing MQTT client: {e}")
            self.catalog_client.unregister()
            raise SystemExit(1)

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def _process_finish_sleep(self, userid, bedroomid, timestamp):
        logger.info(f"Recorded FINISH_SLEEP for user {userid} at {timestamp}")
        logger.debug(f"Retrieving cached sleep time for user {userid}")

        try:
            report = self.startAnalytics(self.cache_sleep_time[userid], bedroomid, userid)
            if report:
                report['user_id'] = userid
                try:
                    dt = datetime.fromtimestamp(timestamp)
                    report['date'] = dt.strftime("%Y-%m-%d")
                    logger.debug(f"Report date set to {report['date']}")
                except Exception as e:
                    logger.error(f"Error parsing timestamp {timestamp}: {e}")
                    report['date'] = datetime.now().strftime("%Y-%m-%d")

                topic = f"BedAnalitics/userid/{userid}/SleepReport"
                logger.debug(f"Publishing sleep report to topic: {topic}")
                self.mqtt_client.myPublish(topic, report)
                logger.info(f"✓ Published analytics report for user {userid} to topic {topic}")
            else:
                logger.error(f"Analytics failed for user {userid} - no report generated")
        except KeyError:
            logger.error(f"ERROR: No START_SLEEP found for user {userid}. Cannot process analytics.")
        except Exception as e:
            logger.error(f"Exception in _process_finish_sleep: {e}", exc_info=True)

    def notify(self, topic, payload):
        if not "SleepReport" in topic:
            try:
                message_received = json.loads(payload)
                action    = message_received.get("action")
                userid    = topic.split("/")[2]
                bedroomid = topic.split("/")[4]
                timestamp = message_received.get("timestamp")

                logger.debug(f"MQTT Message received - Topic: {topic}, Action: {action}, UserID: {userid}")

                if action == "START_SLEEP":
                    self.cache_sleep_time[userid] = {"start": timestamp, "end": None}
                    logger.info(f"✓ START_SLEEP recorded for user {userid} at timestamp {timestamp}")

                elif action == "FINISH_SLEEP":
                    if userid in self.cache_sleep_time and self.cache_sleep_time[userid]["start"] is not None:
                        self.cache_sleep_time[userid]["end"] = timestamp
                        logger.info(f"✓ FINISH_SLEEP recorded for user {userid} at timestamp {timestamp}")
                        logger.debug(f"Sleep duration: {self.cache_sleep_time[userid]['start']} → {timestamp}")
                        # we start a new thread to process the analytics so we don't block if we receive multiple FINISH_SLEEP messages in a short time
                        logger.info(f"Starting analytics thread for user {userid}...")
                        threading.Thread(target=self._process_finish_sleep, args=(userid, bedroomid, timestamp)).start()
                    else:
                        logger.warning(
                            f"Received FINISH_SLEEP for user {userid} without a corresponding START_SLEEP"
                        )
                else:
                    logger.warning(f"Unknown action received: {action} for user {userid}")
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON payload received on topic {topic}")
            except Exception as e:
                logger.error(f"Error processing payload on topic {topic}: {e}", exc_info=True)

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
        start_time = sleep_time.get("start")
        end_time   = sleep_time.get("end")

        if not (start_time and end_time):
            logger.error("Can not start analytics - missing start or end time")
            return None

        logger.info(f"🔍 Starting analytics for sleep period: {start_time} to {end_time} (Bedroom: {bedroomid})")
        raw_data = self.get_data_from_timeseries(bedroomid, start_time, end_time)

        if not raw_data:
            logger.warning(f"No data available for analytics for bedroom {bedroomid}")
            return None

        report = self._elaborate_sleep_analytics(raw_data)

        if "error" in report:
            logger.error(f"Analytics error for bedroom {bedroomid}: {report['error']}")
            return None

        logger.info(f"✓ Analytics completed for user {userid} → Sleep Score: {report['sleep_score']} | "
                    f"Quality: {report['quality']} | Sleep Hours: {report['sleep_hours']} | "
                    f"Wake-ups: {report['wake_ups']} | Resting HR: {report['resting_hr']} bpm | "
                    f"HRV (RMSSD): {report['hrv_rmssd_ms']} ms | Stage %: {report['stage_percent']} ")
        return report

    def _get_sleep_state(self, presence, vibration, heart_rate, rhr, rem_threshold):
        if presence != 1:
            return "AWAKE"
        if abs(vibration) > self.VIBRATION_LIMIT:
            return "AWAKE"
        if heart_rate <= rhr + 3:
            return "DEEP"
        if heart_rate >= rem_threshold:
            return "REM"
        return "LIGHT"

    def _parse_and_cleaning_data(self, raw_data):
        sensors = {}
        for entry in raw_data:
            bn = entry.get("bn", "")
            try:
                sensor_type_id = int(bn.split(":")[-1])
                sensor_name = SENSOR_TYPE.get(sensor_type_id)
            except (ValueError, IndexError):
                self.logger.error(f"Invalid sensor type in bn: {bn}")
                continue
            if sensor_name:
                if sensor_name == "heart_rate":
                    valid_readings = [m for m in entry.get("e", []) if 30 <= m["v"] <= 220]
                    sensors[sensor_name] = valid_readings
                else:
                    sensors[sensor_name] = entry.get("e", [])
        return sensors

    def _classify_sleep_stages(self, presence_list, hr_list, vibration_list, rhr, rem_threshold):
        classified = []
        for m in presence_list:
            t        = m["t"]
            presence = m["v"]
            hr       = _closest_value(hr_list,        t, default=rhr)
            vib      = _closest_value(vibration_list, t, default=0.0)
            stage    = self._get_sleep_state(presence, vib, hr, rhr, rem_threshold)
            classified.append({
                "timestamp": t,
                "stage":     stage,
                "hr":        round(hr, 1),
                "vibration": vib,
                "presence":  presence,
            })
        return classified

    def _get_sleep_score(self, sleep_hours, wake_ups, perceSleepPhase, avg_temp):
        score = 100.0
        if sleep_hours < self.MIN_SLEEP_HOURS:
            score = score - (self.MIN_SLEEP_HOURS - sleep_hours) * 10 # like we sleep 10 hours but we need at least 6.5, we lose 35 points
        if wake_ups > self.MAX_WAKE_UPS:
            score -= (wake_ups - self.MAX_WAKE_UPS) * 5
        if perceSleepPhase["DEEP"] < self.MIN_DEEP_stage_percent:
            score -= (self.MIN_DEEP_stage_percent - perceSleepPhase["DEEP"]) * 0.5
        if perceSleepPhase["REM"] < self.MIN_REM_stage_percent:
            score -= (self.MIN_REM_stage_percent - perceSleepPhase["REM"]) * 0.3
        if avg_temp is not None:
            temp_diff = abs(avg_temp - self.IDEAL_TEMP)
            if temp_diff > self.TEMP_TOLERANCE:
                score -= (temp_diff - self.TEMP_TOLERANCE) * 3
        score = round(max(0.0, min(100.0, score)), 1)

        if score >= 85:
            quality = "Excellent"
        elif score >= 70:
            quality = "Good"
        elif score >= 55:
            quality = "Fair"
        else:
            quality = "Poor"
        return score, quality

    def _elaborate_sleep_analytics(self, raw_data):
        if not raw_data:
            return {"error": "No sensor data available"}
        sensors        = self._parse_and_cleaning_data(raw_data)
        temp_list      = sensors.get("temperature",  [])
        vibration_list = sensors.get("vibration",    [])
        presence_list  = sensors.get("presence",     [])
        hr_list        = sensors.get("heart_rate",   [])

        self.logger.info(f"Sensor data parsed - HR: {len(hr_list)} readings, "
                        f"Presence: {len(presence_list)}, Temp: {len(temp_list)}, "
                        f"Vibration: {len(vibration_list)}")

        if not hr_list:
            return {"error": "No Heart Rate data found"}
        if not presence_list:
            return {"error": "No Presence data found — cannot determine time in bed"}

        rhr, rem_threshold = _compute_hr_thresholds(hr_list)
        self.logger.info(f"HR thresholds calculated - Resting HR: {rhr:.1f} bpm, REM threshold: {rem_threshold:.1f} bpm")

        classified = self._classify_sleep_stages(
            presence_list, hr_list, vibration_list, rhr, rem_threshold
        )
        self.logger.debug(f"Sleep stages classified - Total readings: {len(classified)}")

        counts, stage_percent = _compute_stage_stats(classified)
        self.logger.info(f"Stage distribution - Deep: {stage_percent['DEEP']}%, "
                        f"Light: {stage_percent['LIGHT']}%, REM: {stage_percent['REM']}%, "
                        f"Awake: {stage_percent['AWAKE']}%")

        wake_ups, sleep_hours = _count_wakeups(classified)
        self.logger.info(f"Sleep metrics - Total sleep: {sleep_hours}h, Wake-ups: {wake_ups}")

        hrv_rmssd = _compute_hrv(hr_list)
        self.logger.info(f"HRV (RMSSD) calculated: {hrv_rmssd} ms")

        # Initialize avg_temp to None first
        avg_temp = None
        if temp_list:
            avg_temp = round(
                sum(float(event.get("v", 0.0)) for event in temp_list) / len(temp_list),
                2
            )
            self.logger.info(f"Average room temperature: {avg_temp}°C")
        else:
            self.logger.warning("No temperature data available for analysis")

        self.logger.debug(f"Calling _get_sleep_score with avg_temp={avg_temp}")
        score, quality = self._get_sleep_score(sleep_hours, wake_ups, stage_percent, avg_temp)
        self.logger.info(f"Sleep score calculated: {score}/100 ({quality})")

        return {
            "sleep_score":   score,
            "quality":       quality,
            "sleep_hours":   sleep_hours,
            "wake_ups":      wake_ups,
            "resting_hr":    round(rhr, 1),
            "hrv_rmssd_ms":  hrv_rmssd,
            "stage_percent": stage_percent,
            "stage_minutes": {s: round(counts[s], 1) for s in counts},
        }

if __name__ == "__main__":
    try:
        with open("conf.json", "r") as f:
            full_conf = json.load(f)
    except FileNotFoundError:
        logger.error("Configuration file 'conf.json' not found")
        raise SystemExit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in 'conf.json': {e}")
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Error reading configuration file: {e}")
        raise SystemExit(1)

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
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"Error starting service: {e}")
        raise SystemExit(1)
