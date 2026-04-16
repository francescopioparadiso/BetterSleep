import argparse
import logging
import math
import os
from datetime import date, datetime, timedelta

logging.basicConfig(
    filename='test_cycle.log',
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)
os.remove('test_cycle.log') if os.path.exists('test_cycle.log') else None


from device_connector.Simulate_Sensor import *
from common.MyMQTT import MyMQTT
import requests
from common_simulation import build_url, get_user_service_endpoint, load_json_file, normalize_service_endpoint

SLEEP_CYCLE_LENGTH_MINUTES = 90
RANDOM_AWAKE_PROBABILITY = 0.01
DEFAULT_DURATION_SECONDS = 120
DEFAULT_TARGET_DATE = 1
TEMP_CHANGE_THRESHOLD = 0.3
HR_CHANGE_THRESHOLD = 2.0
VIB_CHANGE_THRESHOLD = 0.002


class MQTTSubscriber:

    def __init__(self, broker, port, userid, houseid, bedroomid, initial_light=50):
        self.broker = broker
        self.port = port
        self.userid = userid
        self.houseid = houseid
        self.bedroomid = bedroomid
        self.actuator_states = {"light": initial_light, "heater": "OFF", "fan": "OFF"}
        self.current_phase = "DAY"
        self.mqtt_client = None
        self.topics = [
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/light/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/heater/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/fan/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/phase"
            ]

    def on_message(self, topic, payload):
        try:
            message_received = json.loads(payload)
            if "actuator" in topic and "data" in topic:
                parts = topic.split("/")
                if len(parts) >= 7:
                    device_type = parts[5]
                    if 'e' in message_received and len(message_received['e']) > 0:
                        value = message_received['e'][0].get('v')
                        self.actuator_states[device_type] = value
            elif "phase" in topic and "actuator" not in topic:
                if 'e' in message_received and len(message_received['e']) > 0:
                    self.current_phase = message_received['e'][0].get('v')
        except Exception as e:
            logger.error(f"Error parsing MQTT message on topic {topic}: {e}")

    def start(self):
        try:
            client_id = f"TestCycleMonitor_{self.userid}_{int(time.time())}"
            self.mqtt_client = MyMQTT(client_id, self.broker, self.port, self)
            self.mqtt_client.start()
            for topic in self.topics:
                self.mqtt_client.mySubscribe(topic)
                logger.info(f"[User {self.userid}] Subscribed to: {topic}")
        except Exception as e:
            logger.error(f"Error starting MQTT feedback monitor: {e}")

    def stop(self):
        if self.mqtt_client:
            self.mqtt_client.stop()

    def notify(self, topic, payload):
        self.on_message(topic, payload)

    def get_states(self):
        return {
            "light": self.actuator_states.get("light", "?"),
            "heater": self.actuator_states.get("heater", "?"),
            "fan": self.actuator_states.get("fan", "?"),
            "phase": self.current_phase if self.current_phase else "DAY"
        }


class SleepWindow:
    def __init__(self, label, sleep_start, sleep_end, sim_start, sim_minutes, sleep_minutes):
        self.label = label
        self.sleep_start = sleep_start
        self.sleep_end = sleep_end
        self.sim_start = sim_start
        self.sim_minutes = sim_minutes
        self.sleep_minutes = sleep_minutes


class UserContext:
    def __init__(self, userid, houseid, bedroomid, night_time, morning_time):
        self.userid = userid
        self.houseid = houseid
        self.bedroomid = bedroomid
        self.night_time = night_time
        self.morning_time = morning_time


def load_test_config(config_path="conf.json"):
    return load_json_file(config_path)


def _get_user_service_endpoint(catalog_url):
    try:
        return get_user_service_endpoint(catalog_url)
    except Exception as exc:
        logger.error(f"Error getting UserService endpoint from Catalog: {exc}")
    return None


def fetch_users_from_user_service(config):
    catalog_url = config["catalog"]["url"]
    us_endpoint = _get_user_service_endpoint(catalog_url)
    if not (requests and us_endpoint):
        logger.warning("Falling back to users from conf.json (user service unavailable)")
        return config.get("users", [config["simulation"]])

    try:
        users_res = requests.get(f"{us_endpoint}/getAllUsers", timeout=5)
        users_payload = users_res.json() if users_res.status_code == 200 else {}
        user_list = users_payload.get("users", [])
    except Exception as exc:
        logger.error(f"Error fetching users from UserService: {exc}")
        return config.get("users", [config["simulation"]])

    try:
        active_res = requests.get(f"{us_endpoint}/getActiveRoomsWithUser", timeout=5)
        active_payload = active_res.json() if active_res.status_code == 200 else {}
        active_rooms = active_payload.get("active_rooms", {}) or {}
    except Exception:
        active_rooms = {}

    discovered = []
    for user in user_list:
        uid = str(user.get("id") or user.get("userid") or "").strip()
        if not uid:
            continue

        room_id = active_rooms.get(uid) or active_rooms.get(int(uid)) if isinstance(active_rooms, dict) else None
        room_info = None

        try:
            if room_id:
                room_res = requests.get(f"{us_endpoint}/getRoomById?room_id={room_id}", timeout=5)
                if room_res.status_code == 200:
                    room_info = room_res.json()
        except Exception:
            room_info = None

        if not room_info:
            try:
                active_res = requests.get(f"{us_endpoint}/getActiveRoom?user_id={uid}", timeout=5)
                if active_res.status_code == 200:
                    room_info = active_res.json().get("active_room") or active_res.json()
            except Exception:
                room_info = None

        houseid = str(room_info.get("house_id")) if room_info and room_info.get("house_id") is not None else None
        bedroomid = str(room_info.get("id")) if room_info and room_info.get("id") is not None else None

        if houseid and bedroomid:
            discovered.append({"userid": uid, "houseid": houseid, "bedroomid": bedroomid})
        else:
            logger.warning(f"User {uid} has no active room; skipping for simulation")

    if not discovered:
        logger.warning("No active users discovered; falling back to users from conf.json")
        return config.get("users", [config["simulation"]])
    return discovered


def build_user_contexts(config, selected_user_ids=None):
    users = fetch_users_from_user_service(config)
    selected_user_ids = {str(user_id) for user_id in (selected_user_ids or [])}
    contexts = []
    for user_info in users:
        userid = str(user_info.get("userid") or user_info.get("id") or "").strip()
        if selected_user_ids and userid not in selected_user_ids:
            continue
        houseid = str(user_info.get("houseid") or user_info.get("house_id") or "").strip()
        bedroomid = str(user_info.get("bedroomid") or user_info.get("bedroom_id") or user_info.get("roomid") or "").strip()
        night, morning = get_user_sleep_times(config["catalog"]["url"], userid) if userid else ("22:00", "07:00")
        contexts.append(UserContext(
            userid=userid or "unknown",
            houseid=houseid or "1",
            bedroomid=bedroomid or "1",
            night_time=night,
            morning_time=morning
        ))
    return contexts


def default_night_bases(target_date=None):
    normalized_target_date = normalize_target_date(target_date)
    if normalized_target_date:
        return [(
            f"{normalized_target_date.strftime('%Y%m%d')}_to_{(normalized_target_date + timedelta(days=1)).strftime('%Y%m%d')}",
            normalized_target_date
        )]

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    return [
        (f"{two_days_ago.strftime('%Y%m%d')}_to_{(two_days_ago + timedelta(days=1)).strftime('%Y%m%d')}", two_days_ago),
        (f"{yesterday.strftime('%Y%m%d')}_to_{today.strftime('%Y%m%d')}", yesterday),
    ]


def normalize_target_date(target_date):
    """Normalize input date to a date object.

    Supported formats:
    - None: use default two-night behavior
    - int: day offset from today (1 = yesterday)
    - str: YYYY-MM-DD
    - datetime/date objects
    """
    if target_date is None:
        return None

    if isinstance(target_date, int):
        return datetime.now().date() - timedelta(days=max(0, target_date))

    if isinstance(target_date, str):
        try:
            return datetime.strptime(target_date, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid target_date string '{target_date}', expected YYYY-MM-DD. Using default nights.")
            return None

    if isinstance(target_date, datetime):
        return target_date.date()

    if isinstance(target_date, date):
        return target_date

    logger.warning(f"Unsupported target_date type '{type(target_date).__name__}'. Using default nights.")
    return None


def build_sleep_window(night_str, morning_str, base_date, label):
    night_hr, night_min = map(int, night_str.split(":"))
    morning_hr, morning_min = map(int, morning_str.split(":"))

    sleep_start = datetime.combine(base_date, datetime.min.time()).replace(hour=night_hr, minute=night_min)
    sleep_end = datetime.combine(base_date, datetime.min.time()).replace(hour=morning_hr, minute=morning_min)
    if sleep_end <= sleep_start:
        sleep_end += timedelta(days=1)

    sim_start = sleep_start - timedelta(hours=1)
    sleep_minutes = int((sleep_end - sleep_start).total_seconds() / 60)
    sim_minutes = sleep_minutes + 120

    return SleepWindow(
        label=label,
        sleep_start=sleep_start,
        sleep_end=sleep_end,
        sim_start=sim_start,
        sim_minutes=sim_minutes,
        sleep_minutes=sleep_minutes,
    )


def build_sleep_windows(night_str, morning_str, bases=None):
    bases = bases or default_night_bases()
    return [build_sleep_window(night_str, morning_str, base_date, label) for label, base_date in bases]


def get_sleep_phase(minute_of_night):
    if minute_of_night < 0:
        return "AWAKE"
    if random.random() < RANDOM_AWAKE_PROBABILITY:
        return "AWAKE"

    cycle_number = minute_of_night // SLEEP_CYCLE_LENGTH_MINUTES
    minute_in_cycle = minute_of_night % SLEEP_CYCLE_LENGTH_MINUTES

    deep_duration = max(0, 30 - (cycle_number * 10))
    rem_duration = min(40, 15 + (cycle_number * 10))

    light1_end = 20
    deep_end = light1_end + deep_duration
    light2_end = 90 - rem_duration

    if minute_in_cycle < light1_end:
        return "LIGHT"
    if minute_in_cycle < deep_end:
        return "DEEP"
    if minute_in_cycle < light2_end:
        return "LIGHT"
    return "REM"


def get_hr_for_sleep_phase(sleep_phase, step, resting_hr=58.0):
    low_freq = math.sin(step * 0.3) * 1.5
    high_freq_noise = random.uniform(-4.0, 4.0)
    noise = low_freq + high_freq_noise

    if sleep_phase == "AWAKE":
        return resting_hr + 15 + noise + random.uniform(0, 5)
    if sleep_phase == "LIGHT":
        return resting_hr + 4 + noise
    if sleep_phase == "DEEP":
        return resting_hr + 1 + (noise * 0.5)
    if sleep_phase == "REM":
        return resting_hr + 10 + (noise * 1.5)
    return resting_hr


def get_vibration_for_sleep_phase(sleep_phase, step):
    if sleep_phase == "AWAKE":
        base = 0.08 + 0.05 * abs(math.sin(step * 0.5))
    elif sleep_phase == "LIGHT":
        base = 0.004 + 0.003 * abs(math.sin(step * 0.4))
    elif sleep_phase == "DEEP":
        base = 0.001 + 0.001 * abs(math.sin(step * 0.1))
    elif sleep_phase == "REM":
        base = 0.003 + 0.003 * abs(math.sin(step * 0.9))
    else:
        base = 0.0
    return round(base, 4)


def get_user_sleep_times(catalog_url, userid):
    default_night = "22:00"
    default_morning = "07:00"
    try:
        us_endpoint = get_user_service_endpoint(catalog_url)
        if us_endpoint:
            users_res = requests.get(f"{us_endpoint}/getAllUsers", timeout=5)
            if users_res.status_code == 200:
                users = users_res.json().get("users", [])
                user_match = next(
                    (
                        user for user in users
                        if str(user.get("id")) == str(userid)
                    ),
                    None
                )
                if user_match:
                    return (
                        user_match.get("night_time", default_night),
                        user_match.get("morning_time", default_morning)
                    )

            pref_res = requests.get(f"{us_endpoint}/getUserRoomPreferences?user_id={userid}", timeout=5)
            if pref_res.status_code == 200:
                prefs = pref_res.json().get("preferences", {})
                return prefs.get("night_time", default_night), prefs.get("morning_time", default_morning)
    except Exception as e:
        logger.error(f"Error fetching user preferences for user {userid}: {e}")
    return default_night, default_morning


def _init_output_file(filepath, user, window):
    """Create the SimulationStats directory and write the header line."""
    if not os.path.exists("SimulationStats"):
        os.makedirs("SimulationStats")
    with open(filepath, "w") as f:
        f.write(
            f"Simulation Stats for User {user.userid} | "
            f"House {user.houseid} Bedroom {user.bedroomid} | "
            f"Window {window.label}\n"
        )


def _build_sensors(config, user, window, simulated_timestamp):
    """Instantiate all sensor objects and attach the shared timestamp provider."""
    catalog_url = config["catalog"]["url"]
    broker_ip   = config["mqtt"]["broker"]
    port        = config["mqtt"]["port"]
    sensors_cfg = config["sensors"]

    def make_cfg(cfg, **extra):
        return create_config(
            catalog_url, cfg["sensorID"], cfg["name"], cfg["type"],
            user.houseid, user.bedroomid, broker_ip, port, **extra
        )

    t_cfg  = sensors_cfg["temperature"]
    hr_cfg = sensors_cfg["heart_rate"]
    p_cfg  = sensors_cfg["presence"]
    v_cfg  = sensors_cfg["vibration"]

    temp_sensor      = TemperatureSensor(make_cfg(t_cfg,  topic_publish=t_cfg["topic_publish"]))
    heart_rate_sensor = HeartRateSensor(make_cfg(hr_cfg, topic_publish=hr_cfg["topic_publish"],
                                                          topic_subscribe=hr_cfg["topic_subscribe"]))
    presence_sensor  = PresenceSensor(make_cfg(p_cfg,  topic_publish=p_cfg["topic_publish"]))
    vibration_sensor = VibrationSensor(make_cfg(v_cfg,  topic_publish=v_cfg["topic_publish"]))

    for sensor in (temp_sensor, heart_rate_sensor, vibration_sensor, presence_sensor):
        sensor.timestamp_provider = simulated_timestamp

    return temp_sensor, heart_rate_sensor, presence_sensor, vibration_sensor


def _build_actuators(config, user, simulated_timestamp):
    """Instantiate all actuator objects and attach the shared timestamp provider."""
    catalog_url   = config["catalog"]["url"]
    broker_ip     = config["mqtt"]["broker"]
    port          = config["mqtt"]["port"]
    actuators_cfg = config["actuators"]

    def make_cfg(cfg):
        return create_config(
            catalog_url, cfg["actuatorID"], cfg["name"], cfg["type"],
            user.houseid, user.bedroomid, broker_ip, port,
            topic_publish=cfg["topic_publish"],
            topic_subscribe=cfg["topic_subscribe"],
            is_sensor=False
        )

    fan_actuator    = FanActuator(make_cfg(actuators_cfg["fan"]))
    heater_actuator = HeaterActuator(make_cfg(actuators_cfg["heater"]))
    light_actuator  = LightActuator(make_cfg(actuators_cfg["light"]))

    for actuator in (fan_actuator, heater_actuator, light_actuator):
        actuator.timestamp_provider = simulated_timestamp

    light_actuator.value = 50
    light_actuator.publish_data(light_actuator.value, unit="%", name="LightLevel")

    return fan_actuator, heater_actuator, light_actuator


def _make_baseline_temp_fn(window):
    """Return a callable(minute) -> baseline_temperature for thermal dynamics."""
    sleep_end_min   = max(1, 60 + window.sleep_minutes)
    total_minutes   = window.sim_minutes
    morning_duration = max(1, total_minutes - sleep_end_min)

    def get_baseline_temp(minute):
        if minute <= sleep_end_min:
            return 23 - (5.0 / sleep_end_min) * minute
        return 18 + (4.0 / morning_duration) * (minute - sleep_end_min)

    return get_baseline_temp


def _update_temperature(current_temp, baseline_temp, fan_on, heater_on, thermal_config):
    """Apply one step of the thermal model and return the clamped new temperature."""
    current_temp += (baseline_temp - current_temp) * thermal_config["ambient_pull_factor"]
    if fan_on:
        current_temp -= thermal_config["fan_cooling_per_min"]
    if heater_on:
        current_temp += thermal_config["heater_warming_per_min"]
    return max(thermal_config["min_temp"], min(thermal_config["max_temp"], current_temp))


def _publish_sensor_readings(sensors, step, window, current_temp, sim_ts, mqtt_states=None):
    """
    Publish one tick of sensor data and return the computed
    (presence_value, sleep_phase, heart_rate_value, vibration_value).
    """
    temp_sensor, heart_rate_sensor, presence_sensor, vibration_sensor = sensors

    temp_sensor.value = current_temp
    temp_sensor.publish_data(round(current_temp, 2), unit="degC", timestamp=sim_ts)

    vt = window.sim_start + timedelta(minutes=step)
    presence_value = 1 if (window.sleep_start <= vt < window.sleep_end) else 0
    current_phase = (mqtt_states or {}).get("phase")
    if current_phase == "DAY" and presence_value == 1:
        presence_value = 0
    presence_sensor.publish_data(presence_value, timestamp=sim_ts)

    minute_of_night = int((vt - window.sleep_start).total_seconds() / 60)
    sleep_phase = get_sleep_phase(minute_of_night) if presence_value == 1 else "AWAKE"

    heart_rate_value = get_hr_for_sleep_phase(sleep_phase, step)
    vibration_value  = get_vibration_for_sleep_phase(sleep_phase, step)

    heart_rate_sensor.publish_data(round(heart_rate_value, 2), unit="bpm", timestamp=sim_ts)
    vibration_sensor.publish_data(round(vibration_value, 4),  unit="g",   timestamp=sim_ts)

    return presence_value, sleep_phase, heart_rate_value, vibration_value


def _log_step(filepath, user, window, step, current_temp, presence_value,
              heart_rate_value, vibration_value, sleep_phase, mqtt_states):
    """Format, print and append one simulation-step line to the stats file."""
    vt_str      = (window.sim_start + timedelta(minutes=step)).strftime("%Y-%m-%d %H:%M")
    heater_str  = "ON" if mqtt_states.get("heater") == 1 else "OFF"
    fan_str     = "ON" if mqtt_states.get("fan")    == 1 else "OFF"
    light_val   = mqtt_states.get("light", "?")
    phase       = mqtt_states.get("phase", "DAY")

    line = (
        f"[User {user.userid} | {vt_str}] Sleep Phase={sleep_phase:<5} "
        f"Temp={current_temp:.2f}°C, Pres={int(presence_value)}, "
        f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.4f}g | "
        f"Phase={phase} | MQTT[L={light_val}, F={fan_str}, H={heater_str}]\n"
    )
    print(line, end="")
    with open(filepath, "a") as f:
        f.write(line)


def _teardown_components(components, mqtt_monitor, userid):
    """Gracefully stop all sensors, actuators and the MQTT monitor."""
    for comp in components:
        try:
            if hasattr(comp, 'stop') and callable(comp.stop):
                comp.stop()
        except Exception as e:
            logger.exception(f"Error stopping component for user {userid}: {e}")
    try:
        mqtt_monitor.stop()
    except Exception:
        logger.exception("Error stopping MQTT monitor")


def simulate_single_user_night(user, config, window, duration_seconds, stop_event):
    filepath = f"SimulationStats/SimulationStats_User{user.userid}_{window.label}.txt"
    logger.info(
        f"Starting simulation ({window.label}) for user {user.userid} "
        f"in house {user.houseid}, bedroom {user.bedroomid}"
    )

    _init_output_file(filepath, user, window)

    _sim_step = [0]

    def simulated_timestamp():
        return (window.sim_start + timedelta(minutes=_sim_step[0])).timestamp()

    sensors  = _build_sensors(config, user, window, simulated_timestamp)
    fan_actuator, heater_actuator, light_actuator = _build_actuators(config, user, simulated_timestamp)

    mqtt_monitor = MQTTSubscriber(
        config["mqtt"]["broker"], config["mqtt"]["port"],
        user.userid, user.houseid, user.bedroomid, initial_light=50
    )
    mqtt_monitor.start()
    time.sleep(2)

    thermal_config    = config["thermal_dynamics"]
    get_baseline_temp = _make_baseline_temp_fn(window)
    steps             = max(window.sim_minutes, 1)
    real_step_seconds = duration_seconds / steps
    current_temp      = thermal_config["starting_temp"]

    try:
        for step in range(steps):
            if stop_event.is_set():
                break

            _sim_step[0] = step
            baseline_temp = get_baseline_temp(step)
            fan_on        = getattr(fan_actuator,    'state', 'OFF') == "ON"
            heater_on     = getattr(heater_actuator, 'state', 'OFF') == "ON"

            current_temp = _update_temperature(current_temp, baseline_temp, fan_on, heater_on, thermal_config)
            sim_ts       = simulated_timestamp()
            mqtt_states  = mqtt_monitor.get_states()

            presence_value, sleep_phase, heart_rate_value, vibration_value = _publish_sensor_readings(
                sensors, step, window, current_temp, sim_ts, mqtt_states
            )

            _log_step(
                filepath, user, window, step,
                current_temp, presence_value, heart_rate_value, vibration_value,
                sleep_phase, mqtt_states
            )

            time.sleep(real_step_seconds)

    finally:
        all_components = (*sensors, fan_actuator, heater_actuator, light_actuator)
        _teardown_components(all_components, mqtt_monitor, user.userid)


def delete_previous_simulation_data(config, userid, room_id, date_str, start_time, end_time):
    catalog_url = config["catalog"]["url"]
    print(f"\n[*] Attempting to delete old data for User {userid}, Room {room_id} on {date_str}...")

    try:
        cat_res = requests.get(f"{catalog_url}/catalog/services/time_series?scope=external", timeout=5)
        if cat_res.status_code == 200:
            data_endpoint = normalize_service_endpoint(cat_res.json().get("endpoint"))
            if data_endpoint:
                delete_url = (
                    f"{data_endpoint}/deleteSleepData"
                    f"?user_id={userid}"
                    f"&room_id={room_id}"
                    f"&date={date_str}"
                    f"&start_time={int(start_time)}"
                    f"&end_time={int(end_time)}"
                )
                print(f"[*] Sending DELETE request to: {delete_url}")
                res = requests.delete(delete_url, timeout=5)
                if res.status_code in [200, 204]:
                    print(
                        f"[*] SUCCESS: Cleared previous database records for "
                        f"User {userid}, Room {room_id} on {date_str}\n"
                    )
                else:
                    print(f"[!] FAILED: Backend returned HTTP {res.status_code}. (Did you add the Flask route?)\n")
            else:
                print("[!] FAILED: Could not find Data Service 'endpoint' in Catalog JSON response.\n")
        else:
            print(f"[!] FAILED: Could not reach Catalog. HTTP {cat_res.status_code}\n")
    except Exception as e:
        print(f"[!] ERROR: Something crashed while calling the delete endpoint: {e}\n")


def run_simulation(duration_seconds=60, target_date=None, selected_user_ids=None):
    config        = load_test_config()
    user_contexts = build_user_contexts(config, selected_user_ids=selected_user_ids)
    normalized_target_date = normalize_target_date(target_date)
    bases         = default_night_bases(normalized_target_date)

    if not user_contexts:
        logger.warning("No users to simulate. Exiting.")
        return

    print(f"--- Starting Simulation for {len(user_contexts)} users across {len(bases)} nights ---")

    stop_event = threading.Event()
    threads    = []

    def _run_user(user_ctx):
        windows = build_sleep_windows(user_ctx.night_time, user_ctx.morning_time, bases)
        for window in windows:
            if stop_event.is_set():
                break
            if normalized_target_date:
                date_str = normalized_target_date.strftime("%Y-%m-%d")
                start_time = window.sim_start.timestamp()
                end_time = (window.sim_start + timedelta(minutes=window.sim_minutes)).timestamp()
                delete_previous_simulation_data(
                    config,
                    user_ctx.userid,
                    user_ctx.bedroomid,
                    date_str,
                    start_time,
                    end_time,
                )
                time.sleep(1)
            simulate_single_user_night(user_ctx, config, window, duration_seconds, stop_event)

    for user_ctx in user_contexts:
        t = threading.Thread(target=_run_user, name=f"Thread-User-{user_ctx.userid}", args=(user_ctx,))
        threads.append(t)
        t.start()

    try:
        for t in threads:
            t.join()
        print("\nAll simulations completed.")
    except KeyboardInterrupt:
        print("\nStopping all simulations...")
        stop_event.set()
        for t in threads:
            t.join()
        print("All simulations stopped.")


def main():
    parser = argparse.ArgumentParser(description="Run the BetterSleep night simulation")
    parser.add_argument(
        "--target-date",
        dest="target_date",
        default=DEFAULT_TARGET_DATE,
        help="Night base date in YYYY-MM-DD format"
    )
    parser.add_argument(
        "--duration-seconds",
        dest="duration_seconds",
        type=int,
        default=DEFAULT_DURATION_SECONDS,
        help="Real-time duration of the simulation run"
    )
    parser.add_argument(
        "--user-ids",
        dest="user_ids",
        default="",
        help="Comma-separated list of user ids to simulate"
    )
    args = parser.parse_args()

    selected_user_ids = [user_id.strip() for user_id in args.user_ids.split(",") if user_id.strip()]
    run_simulation(
        duration_seconds=args.duration_seconds,
        target_date=args.target_date,
        selected_user_ids=selected_user_ids,
    )


if __name__ == "__main__":
    main()
