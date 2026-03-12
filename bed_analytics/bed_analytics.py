import json
import sys
import threading
import logging
from datetime import datetime
import time
import cherrypy
import os
import re
from collections import defaultdict

import numpy as np
import requests
from pymongo import MongoClient
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from common.catalog_client import CatalogClient
from common.MQTT.MyMQTT import MyMQTT
from common.common import json_error_page, mqtt_to_regex

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def apply_env_overrides(conf: dict) -> dict:
    conf = json.loads(json.dumps(conf))

    conf["catalogURL"] = os.getenv("BED_ANALYTICS_CATALOG_URL", conf.get("catalogURL"))
    conf["skipCatalog"] = os.getenv("BED_ANALYTICS_SKIP_CATALOG", str(conf.get("skipCatalog", False))).lower() in {"1", "true", "yes", "on"}
    conf.setdefault("MQTT", {})
    conf["MQTT"]["broker"] = os.getenv("BED_ANALYTICS_MQTT_BROKER", conf["MQTT"].get("broker"))
    mqtt_port = os.getenv("BED_ANALYTICS_MQTT_PORT")
    if mqtt_port:
        conf["MQTT"]["port"] = int(mqtt_port)

    mongo_conf = conf.setdefault("mongoDB", {})
    mongo_conf["host"] = os.getenv("BED_ANALYTICS_MONGO_HOST", mongo_conf.get("host"))
    mongo_port = os.getenv("BED_ANALYTICS_MONGO_PORT")
    if mongo_port:
        mongo_conf["port"] = int(mongo_port)
    mongo_conf["username"] = os.getenv("BED_ANALYTICS_MONGO_USERNAME", mongo_conf.get("username"))
    mongo_conf["password"] = os.getenv("BED_ANALYTICS_MONGO_PASSWORD", mongo_conf.get("password"))
    mongo_conf["database"] = os.getenv("BED_ANALYTICS_MONGO_DATABASE", mongo_conf.get("database"))

    return conf


# ─────────────────────────────────────────────
#  SLEEP ANALYTICS ENGINE
# ─────────────────────────────────────────────

IDEAL_TEMP      = 20.0   # °C  — comfortable sleep temperature
VIBRATION_LIMIT = 0.01   # g   — movements above this = restless

# Sensor type map — last number in bn (e.g. "2:2:32:2" → type 2 → "presence")
SENSOR_TYPE = {
    0: "temperature",
    1: "humidity",
    2: "presence",
    3: "heart_rate",
    4: "vibration",
}


def parse_sensor_data(raw_data: list) -> dict:
    """
    Turn the raw SenML list into a simple dict:
      { "heart_rate": [(t, v), ...], "vibration": [...], ... }

    bn format: "roomid:userid:deviceid:sensortype"
    """
    sensors = defaultdict(list)
    for entry in raw_data:
        bn = entry.get("bn", "")
        try:
            sensor_type_id = int(bn.split(":")[-1])
            sensor_name    = SENSOR_TYPE.get(sensor_type_id)
        except (ValueError, IndexError):
            logger.warning(f"Could not parse sensor type from bn: '{bn}', skipping")
            continue

        if sensor_name is None:
            logger.warning(f"Unknown sensor type {sensor_type_id} in bn: '{bn}', skipping")
            continue

        for m in entry.get("e", []):
            sensors[sensor_name].append((m["t"], m["v"]))

    for name in sensors:
        sensors[name].sort(key=lambda x: x[0])

    return sensors


def _closest_value(data_list: list, target_time: float, default):
    """Return the value from data_list whose timestamp is closest to target_time."""
    if not data_list:
        return default
    return min(data_list, key=lambda x: abs(x[0] - target_time))[1]


def compute_hrv_rmssd(hr_values: list) -> float:
    """
    Compute HRV as RMSSD (Root Mean Square of Successive Differences).

    HR (bpm) → R-R intervals (ms) → RMSSD.
    A higher RMSSD indicates greater heart rate variability (better recovery).
    """
    valid_hr = [hr for hr in hr_values if hr > 0]
    if len(valid_hr) < 2:
        return 0.0
    rr = np.array([60_000.0 / hr for hr in valid_hr])
    diffs = np.diff(rr)
    rmssd = float(np.sqrt(np.mean(diffs ** 2)))
    return round(rmssd, 1)


def classify_sleep_stages(hr_list: list, vibration_list: list, presence_list: list) -> list:
    """
    Classify each HR reading into AWAKE / LIGHT / DEEP / REM.

    Strategy
    --------
    1. Any reading where presence ≠ 1 or vibration > VIBRATION_LIMIT → AWAKE.
    2. For the remaining in-bed, still readings use KMeans(k=3) on
       [standardised HR, standardised vibration]:
         - Cluster with lowest HR centroid  → DEEP
         - Cluster with highest HR centroid → REM
         - Middle cluster                   → LIGHT
    3. Falls back to adaptive rule-based classification when fewer than
       10 in-bed readings are available (not enough data for KMeans).
    """
    classified = []
    in_bed_indices = []
    features = []

    min_hr = min((v for _, v in hr_list), default=60.0)

    for i, (t, hr) in enumerate(hr_list):
        presence  = _closest_value(presence_list,  t, default=1)
        vibration = _closest_value(vibration_list, t, default=0.0)

        if presence != 1 or abs(vibration) > VIBRATION_LIMIT:
            stage = "AWAKE"
        else:
            stage = None           # resolved below
            in_bed_indices.append(i)
            features.append([hr, abs(vibration)])

        classified.append({
            "timestamp": t, "stage": stage,
            "hr": hr, "vibration": vibration, "presence": presence,
        })

    if not in_bed_indices:
        return classified

    if len(in_bed_indices) >= 10:
        # ── KMeans path ───────────────────────────────────────────────────────
        X = np.array(features)
        scaler   = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        kmeans = KMeans(n_clusters=3, n_init=10, random_state=42)
        labels = kmeans.fit_predict(X_scaled)

        # Recover HR centroids in original space to name clusters
        centroids_orig = scaler.inverse_transform(kmeans.cluster_centers_)
        hr_order = np.argsort(centroids_orig[:, 0])          # sort by HR

        cluster_to_stage = {
            int(hr_order[0]): "DEEP",
            int(hr_order[1]): "LIGHT",
            int(hr_order[2]): "REM",
        }
        for list_idx, cluster_label in zip(in_bed_indices, labels):
            classified[list_idx]["stage"] = cluster_to_stage[int(cluster_label)]
    else:
        # ── Rule-based fallback ───────────────────────────────────────────────
        for idx in in_bed_indices:
            hr = classified[idx]["hr"]
            if hr <= min_hr + 5:
                classified[idx]["stage"] = "DEEP"
            elif hr > 70:
                classified[idx]["stage"] = "REM"
            else:
                classified[idx]["stage"] = "LIGHT"

    return classified


def _count_interruptions(stages: list) -> int:
    """
    Count AWAKE segments that occur *between* sleep epochs (not at the borders).
    Each AWAKE run surrounded by sleep on both sides counts as one interruption.
    """
    first_sleep = next((i for i, s in enumerate(stages)         if s != "AWAKE"), None)
    last_sleep  = next((i for i, s in enumerate(reversed(stages)) if s != "AWAKE"), None)
    if first_sleep is None or last_sleep is None:
        return 0

    last_sleep_idx = len(stages) - 1 - last_sleep
    core = stages[first_sleep: last_sleep_idx + 1]

    interruptions, in_awake = 0, False
    for s in core:
        if s == "AWAKE" and not in_awake:
            interruptions += 1
            in_awake = True
        elif s != "AWAKE":
            in_awake = False
    return interruptions


def compute_sleep_analytics(raw_data: list) -> dict:
    """
    Full analytics pipeline:
      parse → classify stages (KMeans) → compute durations → HRV / RHR →
      interruptions → sleep score → quality label → summary.
    """
    if not raw_data:
        return {"error": "No sensor data available"}

    sensors = parse_sensor_data(raw_data)

    vibration_list = sensors.get("vibration",   [])
    presence_list  = sensors.get("presence",    [])
    hr_list        = sensors.get("heart_rate",  [])
    temp_list      = sensors.get("temperature", [])

    if not hr_list:
        return {"error": "No Heart Rate data found"}

    # ── Classify every HR reading ─────────────────────────────────────────────
    classified = classify_sleep_stages(hr_list, vibration_list, presence_list)

    # ── Per-reading durations (actual timestamps, not assumed interval) ───────
    timestamps    = [r["timestamp"] for r in classified]
    durations_min = []
    for i in range(len(timestamps)):
        if i < len(timestamps) - 1:
            durations_min.append((timestamps[i + 1] - timestamps[i]) / 60.0)
        else:
            median_d = float(np.median(durations_min)) if durations_min else 1.0
            durations_min.append(median_d)

    # ── Stage durations (minutes) ─────────────────────────────────────────────
    stage_min = {"AWAKE": 0.0, "LIGHT": 0.0, "DEEP": 0.0, "REM": 0.0}
    for reading, dur in zip(classified, durations_min):
        stage_min[reading["stage"]] += dur

    # ── Interruptions ─────────────────────────────────────────────────────────
    stages_seq    = [r["stage"] for r in classified]
    interruptions = _count_interruptions(stages_seq)

    # ── Sleep duration ────────────────────────────────────────────────────────
    sleep_duration_min = round(stage_min["LIGHT"] + stage_min["DEEP"] + stage_min["REM"])
    sleep_hours        = round(sleep_duration_min / 60, 1)

    # ── RHR: lowest HR recorded during any DEEP epoch ────────────────────────
    deep_hrs = [r["hr"] for r in classified if r["stage"] == "DEEP"]
    rhr      = round(min(deep_hrs) if deep_hrs else min(v for _, v in hr_list), 1)

    # ── HRV (RMSSD over all non-AWAKE readings) ───────────────────────────────
    sleep_hr_values = [r["hr"] for r in classified if r["stage"] != "AWAKE"]
    hrv_ms          = compute_hrv_rmssd(sleep_hr_values)

    # ── Stage percentages ─────────────────────────────────────────────────────
    total_min = sum(stage_min.values()) or 1.0
    pct       = {s: round(stage_min[s] / total_min * 100, 1) for s in stage_min}

    # ── Average temperature ───────────────────────────────────────────────────
    avg_temp = (sum(v for _, v in temp_list) / len(temp_list)) if temp_list else None

    # ── Sleep Score (0–100) ───────────────────────────────────────────────────
    score = 100.0
    if sleep_hours < 7:
        score -= (7 - sleep_hours) * 10          # –10 pts per missing hour
    if pct["AWAKE"] > 10:
        score -= (pct["AWAKE"] - 10)             # –1 pt per % above 10 %
    if pct["DEEP"] < 15:
        score -= (15 - pct["DEEP"]) * 0.5        # gentle deep-sleep penalty
    if avg_temp is not None:
        temp_diff = abs(avg_temp - IDEAL_TEMP)
        if temp_diff > 2:
            score -= (temp_diff - 2) * 3         # –3 pts per °C outside comfort
    score = round(max(0.0, min(100.0, score)), 1)

    # ── Quality label ─────────────────────────────────────────────────────────
    if score >= 85:   quality = "Excellent"
    elif score >= 70: quality = "Good"
    elif score >= 55: quality = "Fair"
    else:             quality = "Poor"

    return {
        "sleep_score":       score,
        "quality":           quality,
        "sleep_hours":       sleep_hours,
        "sleep_duration_min": sleep_duration_min,
        "interruptions":     interruptions,
        "rem_sleep_min":     round(stage_min["REM"]),
        "deep_sleep_min":    round(stage_min["DEEP"]),
        "hrv_ms":            hrv_ms,
        "rhr_bpm":           rhr,
        "stage_minutes":     {k: round(v) for k, v in stage_min.items()},
        "stage_percent":     pct,
        "avg_temp_degC":     round(avg_temp, 1) if avg_temp is not None else None,
        "readings":          classified,
        "summary": (
            f"{quality} sleep — {score}/100. "
            f"{sleep_hours}h asleep ({sleep_duration_min} min). "
            f"Deep: {pct['DEEP']}%  REM: {pct['REM']}%  "
            f"Light: {pct['LIGHT']}%  Awake: {pct['AWAKE']}%.  "
            f"Interruptions: {interruptions}.  "
            f"HRV: {hrv_ms} ms  RHR: {rhr} bpm."
        ),
    }


# ─────────────────────────────────────────────
#  BedAnalytics SERVICE
# ─────────────────────────────────────────────

class BedAnalytics:
    exposed = True

    def __init__(self, conf):
        self.logger = logger
        self.conf = conf
        self.catalog_url      = conf['catalogURL']
        self.skip_catalog     = conf.get('skipCatalog', False)
        self.service_info     = conf['serviceInfo']
        self.remove_interval  = conf.get('removeInterval', 10)
        self._stop_event      = threading.Event()
        self._worker          = None
        self.actualTime       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.catalog_client   = None if self.skip_catalog else CatalogClient(self.catalog_url, self.service_info, self.remove_interval)
        if self.catalog_client is not None:
            self.catalog_client.register()
        self.timeseries_endpoint = os.getenv('BED_ANALYTICS_TIMESERIES_ENDPOINT') or self.get_endpoint_timeseries()
        self.user_service_endpoint = os.getenv('BED_ANALYTICS_USER_SERVICE_URL') or self.get_user_service_endpoint()
        self.mqtt_client         = None
        self.MQTT_info           = conf['MQTT']
        self.topic_subscribe_raw   = self.MQTT_info['topic_subscribe']
        self.topic_subscribe_regex = [re.compile(mqtt_to_regex(t)) for t in self.topic_subscribe_raw]
        self.cache_sleep_time  = {}   # {userid: {"start": timestamp, "end": timestamp}}
        self.analytics_results = {}   # {userid: last analytics report}
        self.mongo_db          = self._connect_mongodb(conf)

    def _connect_mongodb(self, conf):
        """Connect to MongoDB and return the analytics database (with retries)."""
        db_conf = conf.get('mongoDB')
        if not db_conf:
            logger.warning("No 'mongoDB' key in conf — nightly summaries will not be persisted")
            return None

        retries = int(db_conf.get('retries', 5))
        delay   = int(db_conf.get('retryDelaySec', 5))

        for attempt in range(1, retries + 1):
            try:
                client = MongoClient(
                    host=db_conf['host'],
                    port=db_conf['port'],
                    username=db_conf['username'],
                    password=db_conf['password'],
                    serverSelectionTimeoutMS=5000,
                )
                client.admin.command('ping')
                logger.info("BedAnalytics connected to MongoDB")
                return client[db_conf['database']]
            except Exception as e:
                logger.error(f"MongoDB connection failed (attempt {attempt}/{retries}): {e}")
                if attempt < retries:
                    time.sleep(delay)

        logger.error("Giving up connecting to MongoDB; analytics persistence disabled")
        return None

    def get_endpoint_timeseries(self):
        if self.catalog_client is None:
            self.logger.warning("Catalog disabled and no time series endpoint provided via environment")
            return None
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

    def get_user_service_endpoint(self):
        if self.catalog_client is None:
            self.logger.warning("Catalog disabled and no user service endpoint provided via environment")
            return None
        data, status, error = self.catalog_client.get("getUserServiceURL")
        if status == 200 and data:
            endpoint = data.get("endpoint") or data.get("url") or data.get("user_service_url")
            if endpoint:
                self.logger.info(f"User service endpoint retrieved: {endpoint}")
                return endpoint
        self.logger.error(f"Error retrieving User Service endpoint: {status} - {error}")
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
            if self.catalog_client is not None:
                self.catalog_client.unregister()
            sys.exit(1)

    def startClient(self):
        self.mqtt_client.start()

    def stopClient(self):
        self.mqtt_client.stop()

    def notify(self, topic, payload):
        try:
            message_received = json.loads(payload)
            action    = message_received.get("action")
            userid    = topic.split("/")[2]
            bedroomid = topic.split("/")[4]
            timestamp = message_received.get("timestamp")

            if timestamp is None:
                logger.warning(f"Ignoring message without timestamp on topic {topic}")
                return

            if action == "START_SLEEP":
                self.cache_sleep_time[userid] = {"start": timestamp, "end": None}
                logger.info(f"Recorded START_SLEEP for user {userid} at {timestamp}")

            elif action == "FINISH_SLEEP":
                if userid in self.cache_sleep_time and self.cache_sleep_time[userid]["start"] is not None:
                    self.cache_sleep_time[userid]["end"] = timestamp
                    logger.info(f"Recorded FINISH_SLEEP for user {userid} at {timestamp}")
                    self.startAnalytics(self.cache_sleep_time[userid], bedroomid, userid)
                else:
                    logger.warning(
                        f"Received FINISH_SLEEP for user {userid} without a corresponding START_SLEEP"
                    )
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON payload received on topic {topic}")

    def get_room_house_id(self, room_id):
        """Fetch the house_id for a given room_id from user service."""
        try:
            user_service_url = self.user_service_endpoint
            if not user_service_url:
                logger.warning("User service URL not available")
                return None
            res = requests.get(f"{user_service_url}/getRoomById?room_id={room_id}")
            if res.status_code == 200:
                room_data = res.json()
                return room_data.get("house_id")
            else:
                logger.warning(f"Failed to fetch room data: {res.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching house_id for room {room_id}: {e}")
            return None

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
        store the result in memory and publish a nightly summary to MongoDB.
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

        report = compute_sleep_analytics(raw_data)

        if "error" in report:
            logger.error(f"Analytics error for bedroom {bedroomid}: {report['error']}")
            return None

        if userid:
            self.analytics_results[userid] = {
                "bedroomid":  bedroomid,
                "start_time": start_time,
                "end_time":   end_time,
                "report":     report,
            }

        logger.info(
            f"Analytics completed for bedroom {bedroomid} | "
            f"Score: {report['sleep_score']}/100 | {report['summary']}"
        )

        house_id = self.get_room_house_id(bedroomid)
        self.publish_night_summary(userid, bedroomid, house_id, start_time, report)
        return report

    def publish_night_summary(self, user_id, room_id, house_id, start_ts, report: dict):
        """
        Upsert a single nightly-summary document into the MongoDB
        'sleep_analytics' collection, keyed by (date, user_id).

        Document fields
        ---------------
        date              – ISO date string of the night (YYYY-MM-DD), derived from start_ts
        user_id           – identifier of the user
        house_id          – house where the bedroom is located
        room_id           – bedroom where the sensors are located
        sleep_score       – float 0–100
        sleep_comment     – quality label (Excellent / Good / Fair / Poor)
        sleep_duration_min– total sleep time in minutes (excluding AWAKE)
        interruptions     – number of AWAKE episodes during the night
        rem_sleep_min     – minutes spent in REM stage
        deep_sleep_min    – minutes spent in DEEP stage
        hrv_ms            – RMSSD heart-rate variability in milliseconds
        rhr_bpm           – resting heart rate (lowest HR in DEEP epochs) in bpm
        summary           – human-readable one-line description
        updated_at        – UTC ISO timestamp of when this document was last written
        """
        if self.mongo_db is None:
            # Retry connection in case MongoDB was not ready during startup
            self.mongo_db = self._connect_mongodb(self.conf)
        if self.mongo_db is None:
            logger.warning("MongoDB not connected — skipping nightly summary publish")
            return
        try:
            date_str = datetime.fromtimestamp(float(start_ts)).strftime("%Y-%m-%d")
            doc = {
                "date":               date_str,
                "user_id":            int(user_id)  if user_id  else None,
                "house_id":           int(house_id) if house_id else None,
                "room_id":            int(room_id)  if room_id  else None,
                "sleep_score":        report["sleep_score"],
                "sleep_comment":      report["quality"],
                "sleep_duration_min": report["sleep_duration_min"],
                "interruptions":      report["interruptions"],
                "rem_sleep_min":      report["rem_sleep_min"],
                "deep_sleep_min":     report["deep_sleep_min"],
                "hrv_ms":             report["hrv_ms"],
                "rhr_bpm":            report["rhr_bpm"],
                "summary":            report["summary"],
                "updated_at":         datetime.utcnow().isoformat(),
            }
            self.mongo_db["sleep_analytics"].replace_one(
                {"date": date_str, "user_id": doc["user_id"]},
                doc,
                upsert=True,
            )
            logger.info(
                f"Nightly summary published to MongoDB: user={user_id} house={house_id} "
                f"room={room_id} date={date_str} score={report['sleep_score']}"
            )
        except Exception as e:
            logger.error(f"Failed to publish nightly summary to MongoDB: {e}")

    # ── Optional REST endpoint: GET /analytics?userid=<id> ───────────────────
    @cherrypy.tools.json_out()
    def GET(self, userid=None):
        if userid and userid in self.analytics_results:
            return self.analytics_results[userid]
        elif userid:
            raise cherrypy.HTTPError(404, f"No analytics found for user '{userid}'")
        # Return all results if no userid specified
        return self.analytics_results


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    try:
        with open("conf.json", "r") as f:
            full_conf = apply_env_overrides(json.load(f))
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
        if bed_analytics.catalog_client is not None:
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
