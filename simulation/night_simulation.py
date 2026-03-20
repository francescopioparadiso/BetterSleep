import argparse
import logging
import math
import os
import sys
import random
from datetime import datetime, timedelta
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(
    filename='test_cycle.log',
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)
os.remove('test_cycle.log') if os.path.exists('test_cycle.log') else None


from device_connector.Simulate_Sensor import *
from common.MyMQTT import MyMQTT
import  requests

SLEEP_CYCLE_LENGTH_MINUTES = 90
RANDOM_AWAKE_PROBABILITY = 0.01

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

    def on_message(self, topic, payload):
        try:
            data = json.loads(payload)
            if "actuator" in topic and "data" in topic:
                parts = topic.split("/")
                if len(parts) >= 7:
                    device_type = parts[5]
                    if 'e' in data and len(data['e']) > 0:
                        value = data['e'][0].get('v')
                        self.actuator_states[device_type] = value
            elif "phase" in topic and "actuator" not in topic:
                if 'e' in data and len(data['e']) > 0:
                    self.current_phase = data['e'][0].get('v')
        except Exception as e:
            logger.error(f"Error parsing MQTT message on topic {topic}: {e}")

    def start(self):
        try:
            client_id = f"TestCycleMonitor_{self.userid}_{int(time.time())}"
            self.mqtt_client = MyMQTT(client_id, self.broker, self.port, self)
            self.mqtt_client.start()
            topics = [
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/light/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/heater/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/fan/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/phase"
            ]
            for topic in topics:
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
    with open(config_path, "r") as f:
        return json.load(f)


def _get_user_service_endpoint(catalog_url):
    if not requests:
        logger.error("requests not available; cannot reach Catalog")
        return None
    try:
        res = requests.get(f"{catalog_url}/getEndpointUserService", timeout=5)
        if res.status_code == 200:
            return res.json().get("endpoint")
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


def build_user_contexts(config):
    users = fetch_users_from_user_service(config)
    contexts = []
    for user_info in users:
        night, morning = get_user_sleep_times(config["catalog"]["url"], user_info["userid"])
        contexts.append(UserContext(
            userid=str(user_info["userid"]),
            houseid=str(user_info["houseid"]),
            bedroomid=str(user_info["bedroomid"]),
            night_time=night,
            morning_time=morning
        ))
    return contexts


def default_night_bases(target_date=None):
    if target_date:
        # Convert string to date if necessary
        if isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        return [(f"{target_date.strftime('%Y%m%d')}_to_{(target_date + timedelta(days=1)).strftime('%Y%m%d')}", target_date)]

    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    return [
        (f"{two_days_ago.strftime('%Y%m%d')}_to_{(two_days_ago + timedelta(days=1)).strftime('%Y%m%d')}", two_days_ago),
        (f"{yesterday.strftime('%Y%m%d')}_to_{today.strftime('%Y%m%d')}", yesterday),
    ]


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

    # Keep occasional interruptions without overwhelming the score model.
    if random.random() < RANDOM_AWAKE_PROBABILITY:
        return "AWAKE"

    cycle_number = minute_of_night // SLEEP_CYCLE_LENGTH_MINUTES
    minute_in_cycle = minute_of_night % SLEEP_CYCLE_LENGTH_MINUTES

    # Deep sleep heavily weighted early night, REM heavily weighted late night
    deep_duration = max(0, 30 - (cycle_number * 10))
    rem_duration = min(40, 15 + (cycle_number * 10))

    # Calculate phase boundaries inside the 90-minute cycle
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
    # Low-frequency wave combined with high-frequency noise for realistic HRV
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
        # REM is characterized by high sympathetic nervous system activity (erratic HR)
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
        cat_res = requests.get(f"{catalog_url}/getEndpointUserService", timeout=5)
        if cat_res.status_code == 200:
            us_endpoint = cat_res.json().get("endpoint")
            if us_endpoint:
                pref_res = requests.get(f"{us_endpoint}/getUserRoomPreferences?user_id={userid}", timeout=5)
                if pref_res.status_code == 200:
                    prefs = pref_res.json().get("preferences", {})
                    return prefs.get("night_time", default_night), prefs.get("morning_time", default_morning)
    except Exception as e:
        logger.error(f"Error fetching user preferences for user {userid}: {e}")
    return default_night, default_morning


def simulate_single_user_night(user, config, window, duration_seconds, stop_event):
    catalog_url = config["catalog"]["url"]
    broker_ip = config["mqtt"]["broker"]
    port = config["mqtt"]["port"]
    sensors_config = config["sensors"]
    actuators_config = config["actuators"]
    thermal_config = config["thermal_dynamics"]
    filepath = f"SimulationStats/SimulationStats_User{user.userid}_{window.label}.txt"

    logger.info(f"Starting simulation ({window.label}) for user {user.userid} in house {user.houseid}, bedroom {user.bedroomid}")
    if not os.path.exists("SimulationStats"):
        os.makedirs("SimulationStats")
    with open(filepath, "w") as f:
        f.write(f"Simulation Stats for User {user.userid} | House {user.houseid} Bedroom {user.bedroomid} | Window {window.label}\n")
    sensor_configs = {}
    t_cfg = sensors_config["temperature"]
    sensor_configs["temp"] = create_config(
        catalog_url, t_cfg['sensorID'], t_cfg["name"], t_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port, topic_publish=t_cfg["topic_publish"]
    )

    hr_cfg = sensors_config["heart_rate"]
    sensor_configs["hr"] = create_config(
        catalog_url, hr_cfg["sensorID"], hr_cfg["name"], hr_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port,
        topic_publish=hr_cfg["topic_publish"],
        topic_subscribe=hr_cfg["topic_subscribe"]
    )

    p_cfg = sensors_config["presence"]
    sensor_configs["presence"] = create_config(
        catalog_url, p_cfg["sensorID"], p_cfg["name"], p_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port, topic_publish=p_cfg["topic_publish"]
    )

    v_cfg = sensors_config["vibration"]
    sensor_configs["vibration"] = create_config(
        catalog_url, v_cfg["sensorID"], v_cfg["name"], v_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port, topic_publish=v_cfg["topic_publish"]
    )

    temp_sensor = TemperatureSensor(sensor_configs["temp"])
    heart_rate_sensor = HeartRateSensor(sensor_configs["hr"])
    presence_sensor = PresenceSensor(sensor_configs["presence"])
    vibration_sensor = VibrationSensor(sensor_configs["vibration"])

    _sim_step = [0]

    def simulated_timestamp():
        vt = window.sim_start + timedelta(minutes=_sim_step[0])
        return vt.timestamp()

    for sensor in (temp_sensor, heart_rate_sensor, vibration_sensor, presence_sensor):
        sensor.timestamp_provider = simulated_timestamp

    l_cfg = actuators_config["light"]
    c_light = create_config(
        catalog_url, l_cfg["actuatorID"], l_cfg["name"], l_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port,
        topic_publish=l_cfg["topic_publish"], topic_subscribe=l_cfg["topic_subscribe"], is_sensor=False
    )

    h_cfg = actuators_config["heater"]
    c_heater = create_config(
        catalog_url, h_cfg["actuatorID"], h_cfg["name"], h_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port,
        topic_publish=h_cfg["topic_publish"], topic_subscribe=h_cfg["topic_subscribe"], is_sensor=False
    )

    f_cfg = actuators_config["fan"]
    c_fan = create_config(
        catalog_url, f_cfg["actuatorID"], f_cfg["name"], f_cfg["type"],
        user.houseid, user.bedroomid, broker_ip, port,
        topic_publish=f_cfg["topic_publish"], topic_subscribe=f_cfg["topic_subscribe"], is_sensor=False
    )

    fan_actuator = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator = LightActuator(c_light)

    for actuator in (fan_actuator, heater_actuator, light_actuator):
        actuator.timestamp_provider = simulated_timestamp

    light_actuator.value = 50
    light_actuator.publish_data(light_actuator.value, unit="%", name="LightLevel")

    mqtt_monitor = MQTTSubscriber(broker_ip, port, user.userid, user.houseid, user.bedroomid, initial_light=50)
    mqtt_monitor.start()

    try:
        time.sleep(2)
        total_minutes = window.sim_minutes
        steps = max(total_minutes, 1)
        real_step_seconds = duration_seconds / steps

        def get_virtual_time(step):
            vt = window.sim_start + timedelta(minutes=step)
            return vt.hour, vt.minute, step

        def get_baseline_temp(minute):
            sleep_end_min = 60 + window.sleep_minutes
            if sleep_end_min <= 0:
                sleep_end_min = 1
            if minute <= sleep_end_min:
                return 23 - (5.0 / sleep_end_min) * minute
            morning_duration = total_minutes - sleep_end_min
            if morning_duration <= 0:
                morning_duration = 1
            return 18 + (4.0 / morning_duration) * (minute - sleep_end_min)

        fan_cooling_per_min = thermal_config["fan_cooling_per_min"]
        heater_warming_per_min = thermal_config["heater_warming_per_min"]
        ambient_pull_factor = thermal_config["ambient_pull_factor"]
        min_temp = thermal_config["min_temp"]
        max_temp = thermal_config["max_temp"]
        current_temp = thermal_config["starting_temp"]

        for step in range(steps):
            if stop_event.is_set():
                break

            _sim_step[0] = step
            hour, minute, virtual_minute = get_virtual_time(step)
            baseline_temp = get_baseline_temp(virtual_minute)

            fan_on = getattr(fan_actuator, 'state', 'OFF') == "ON"
            heater_on = getattr(heater_actuator, 'state', 'OFF') == "ON"

            current_temp += (baseline_temp - current_temp) * ambient_pull_factor
            if fan_on:
                current_temp -= fan_cooling_per_min
            if heater_on:
                current_temp += heater_warming_per_min
            current_temp = max(min_temp, min(max_temp, current_temp))

            sim_ts = simulated_timestamp()

            temp_sensor.value = current_temp
            temp_sensor.publish_data(round(current_temp, 2), unit="degC", timestamp=sim_ts)

            vt = window.sim_start + timedelta(minutes=step)

            presence_value = 1 if (window.sleep_start <= vt < window.sleep_end) else 0
            presence_sensor.publish_data(presence_value, timestamp=sim_ts)

            minute_of_night = int((vt - window.sleep_start).total_seconds() / 60)
            sleep_phase = get_sleep_phase(minute_of_night) if presence_value == 1 else "AWAKE"

            heart_rate_value = get_hr_for_sleep_phase(sleep_phase, step)
            vibration_value = get_vibration_for_sleep_phase(sleep_phase, step)

            heart_rate_sensor.publish_data(round(heart_rate_value, 2), unit="bpm", timestamp=sim_ts)
            vibration_sensor.publish_data(round(vibration_value, 4), unit="g", timestamp=sim_ts)

            mqtt_states = mqtt_monitor.get_states()
            light_mqtt = mqtt_states.get("light", "?")
            heater_mqtt = "ON" if mqtt_states.get("heater") == 1 else "OFF"
            fan_mqtt = "ON" if mqtt_states.get("fan") == 1 else "OFF"
            phase = mqtt_states.get("phase", "DAY")

            vt_str = (window.sim_start + timedelta(minutes=step)).strftime("%Y-%m-%d %H:%M")

            line = (
                f"[User {user.userid} | {vt_str} | {window.label}] Sleep Phase={sleep_phase:<5} "
                f"Temp={current_temp:.2f}°C, Pres={presence_value}, "
                f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.4f}g | "
                f"Phase={phase} | MQTT[L={light_mqtt}, F={fan_mqtt}, H={heater_mqtt}]\n"
            )

            print(line, end="")
            with open(filepath, "a") as f:
                f.write(line)

            time.sleep(real_step_seconds)

    finally:
        for comp in (temp_sensor, heart_rate_sensor, presence_sensor, vibration_sensor,
                     fan_actuator, heater_actuator, light_actuator):
            try:
                if hasattr(comp, 'stop') and callable(getattr(comp, 'stop')):
                    comp.stop()
            except Exception as e:
                logger.exception(f"Error stopping component for user {user.userid}: {e}")
        try:
            mqtt_monitor.stop()
        except Exception:
            logger.exception("Error stopping MQTT monitor")

def delete_previous_simulation_data(config, userid, date_str):
    catalog_url = config["catalog"]["url"]
    print(f"\n[*] Attempting to delete old data for User {userid} on {date_str}...")
    
    try:
        # 1. Ask the Catalog for the service that handles time-series data storage
        cat_res = requests.get(f"{catalog_url}/getEndpointTimeSeries", timeout=5)
        if cat_res.status_code == 200:
            data_endpoint = cat_res.json().get("endpoint")
            if data_endpoint:
                # 2. Send a DELETE request targeting this specific user and date
                delete_url = f"{data_endpoint}/deleteSleepData?user_id={userid}&date={date_str}"
                print(f"[*] Sending DELETE request to: {delete_url}")
                
                res = requests.delete(delete_url, timeout=5)
                
                if res.status_code in [200, 204]:
                    print(f"[*] SUCCESS: Cleared previous database records for User {userid} on {date_str}\n")
                else:
                    print(f"[!] FAILED: Backend returned HTTP {res.status_code}. (Did you add the Flask route?)\n")
            else:
                print("[!] FAILED: Could not find Data Service 'endpoint' in Catalog JSON response.\n")
        else:
             print(f"[!] FAILED: Could not reach Catalog. HTTP {cat_res.status_code}\n")
    except Exception as e:
        print(f"[!] ERROR: Something crashed while calling the delete endpoint: {e}\n")


def run_simulation(duration_seconds=60, target_date=None):
    config = load_test_config()
    user_contexts = build_user_contexts(config)
    
    # Pass target_date to the bases builder
    bases = default_night_bases(target_date)

    if not user_contexts:
        logger.warning("No users to simulate. Exiting.")
        return

    print(f"--- Starting Simulation for {len(user_contexts)} users across {len(bases)} nights ---")

    stop_event = threading.Event()
    threads = []

    def _run_user(user_ctx):
        # If a specific target_date was passed, trigger the database wipe first
        if target_date:
            date_str = target_date if isinstance(target_date, str) else target_date.strftime("%Y-%m-%d")
            delete_previous_simulation_data(config, user_ctx.userid, date_str)
            # Add a tiny delay to ensure the database has time to process the deletion
            time.sleep(1)

        windows = build_sleep_windows(user_ctx.night_time, user_ctx.morning_time, bases)
        for window in windows:
            if stop_event.is_set():
                break
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


def parse_args():
    parser = argparse.ArgumentParser(description="Run the BetterSleep night simulation.")
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=20,
        help="Real-world duration used to compress a simulated night.",
    )
    parser.add_argument(
        "--target-date",
        default=None,
        help="Night base date in YYYY-MM-DD format, for example 2026-10-23.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.target_date:
        try:
            datetime.strptime(args.target_date, "%Y-%m-%d")
        except ValueError as exc:
            raise SystemExit("Invalid --target-date. Use the format YYYY-MM-DD, for example 2026-10-23.") from exc

    run_simulation(duration_seconds=args.duration_seconds, target_date=args.target_date)


if __name__ == "__main__":
    main()
