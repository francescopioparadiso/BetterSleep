import json
import sys
import os
import time
import threading
import logging
import math
from datetime import datetime, timedelta

# Path setups
logging.basicConfig(filename='test_cycle.log', level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

from device_connector.Simulate_Sensor import *
from common.MQTT.MyMQTT import MyMQTT

def load_test_config(config_path="conf.json"):
    with open(config_path, "r") as f:
        return json.load(f)


# ─────────────────────────────────────────────
#  SLEEP STAGE SIMULATOR
#  Simulates a realistic night with ~4 sleep cycles
#  Each cycle (~90 min): Light → Deep → Light → REM
# ─────────────────────────────────────────────

def get_sleep_stage(minute_of_night: int) -> str:
    """
    Returns the expected sleep stage at a given minute after lights out.
    One full sleep cycle is ~90 minutes:
      0–10   min : falling asleep (LIGHT)
      10–30  min : DEEP sleep
      30–50  min : back to LIGHT
      50–80  min : REM
      80–90  min : brief LIGHT before next cycle
    Early cycles have more DEEP; later cycles have more REM.
    """
    if minute_of_night < 0:
        return "AWAKE"

    cycle_length = 90
    cycle_number = minute_of_night // cycle_length      # 0, 1, 2, 3 ...
    minute_in_cycle = minute_of_night % cycle_length

    # Deep sleep shrinks each cycle; REM grows
    deep_end   = max(10, 30 - cycle_number * 7)         # 30 → 23 → 16 → 9 min
    light1_end = deep_end + 15
    rem_end    = light1_end + min(20 + cycle_number * 10, 40)  # 20 → 30 → 40 min

    if minute_in_cycle < 10:
        return "LIGHT"
    elif minute_in_cycle < deep_end:
        return "DEEP"
    elif minute_in_cycle < light1_end:
        return "LIGHT"
    elif minute_in_cycle < rem_end:
        return "REM"
    else:
        return "LIGHT"


def get_hr_for_stage(stage: str, step: int, resting_hr: float = 58.0) -> float:
    """
    Returns a realistic heart rate (bpm) for a given sleep stage.
    Adds a small oscillation so values aren't perfectly flat.

    AWAKE : 72–80 bpm
    LIGHT : 62–68 bpm
    DEEP  : resting_hr to resting_hr+4  (lowest of the night)
    REM   : 66–74 bpm  (elevated and variable, brain is active)
    """
    noise = math.sin(step * 0.3) * 1.5   # gentle oscillation ±1.5 bpm

    if stage == "AWAKE":
        return resting_hr + 16 + noise
    elif stage == "LIGHT":
        return resting_hr + 6 + noise
    elif stage == "DEEP":
        return resting_hr + 1 + abs(noise) * 0.5   # very steady, lowest HR
    elif stage == "REM":
        return resting_hr + 10 + math.sin(step * 0.7) * 3   # more variable
    return resting_hr


def get_vibration_for_stage(stage: str, step: int) -> float:
    """
    Returns a realistic vibration value (g) for a given sleep stage.

    AWAKE : 0.05–0.15 g  (turning, adjusting)
    LIGHT : 0.003–0.007 g (small shifts)
    DEEP  : 0.000–0.002 g (nearly motionless)
    REM   : 0.002–0.006 g (slight twitching — REM behaviour)
    """
    if stage == "AWAKE":
        # Occasional larger movements
        base = 0.08 + 0.05 * abs(math.sin(step * 0.5))
        return round(base, 4)
    elif stage == "LIGHT":
        base = 0.004 + 0.003 * abs(math.sin(step * 0.4))
        return round(base, 4)
    elif stage == "DEEP":
        base = 0.001 + 0.001 * abs(math.sin(step * 0.1))
        return round(base, 4)
    elif stage == "REM":
        # Small twitches
        base = 0.003 + 0.003 * abs(math.sin(step * 0.9))
        return round(base, 4)
    return 0.0


class MQTTFeedbackMonitor:
    """Monitor MQTT feedback from actuators and sleep_cycle_manager."""

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


def simulate_single_user(user_info, config, duration_seconds, stop_event):
    userid    = user_info["userid"]
    houseid   = user_info["houseid"]
    bedroomid = user_info["bedroomid"]

    catalog_url    = config["catalog"]["url"]
    broker_ip      = config["mqtt"]["broker"]
    port           = config["mqtt"]["port"]
    sensors_config = config["sensors"]
    actuators_config = config["actuators"]
    thermal_config = config["thermal_dynamics"]
    filepath = f"SimulationStats_User{userid}.txt"

    logger.info(f"Starting simulation for user {userid} in house {houseid}, bedroom {bedroomid}")
    with open(filepath, "w") as f:
        f.write(f"Simulation Stats for User {userid} | House {houseid} Bedroom {bedroomid}\n")



    # ── Sensors ───────────────────────────────────────────────────────────────
    sensor_configs = {}

    t_cfg = sensors_config["temperature"]
    sensor_configs["temp"] = create_config(catalog_url, t_cfg['sensorID'], t_cfg["name"], t_cfg["type"],
                                           houseid, bedroomid, broker_ip, port, topic_publish=t_cfg["topic_publish"])

    hr_cfg = sensors_config["heart_rate"]
    sensor_configs["hr"] = create_config(catalog_url, hr_cfg["sensorID"], hr_cfg["name"], hr_cfg["type"],
                                         houseid, bedroomid, broker_ip, port,
                                         topic_publish=hr_cfg["topic_publish"],
                                         topic_subscribe=hr_cfg["topic_subscribe"])

    p_cfg = sensors_config["presence"]
    sensor_configs["presence"] = create_config(catalog_url, p_cfg["sensorID"], p_cfg["name"], p_cfg["type"],
                                               houseid, bedroomid, broker_ip, port, topic_publish=p_cfg["topic_publish"])

    v_cfg = sensors_config["vibration"]
    sensor_configs["vibration"] = create_config(catalog_url, v_cfg["sensorID"], v_cfg["name"], v_cfg["type"],
                                                houseid, bedroomid, broker_ip, port, topic_publish=v_cfg["topic_publish"])

    temp_sensor       = TemperatureSensor(sensor_configs["temp"])
    heart_rate_sensor = HeartRateSensor(sensor_configs["hr"])
    presence_sensor   = PresenceSensor(sensor_configs["presence"])
    vibration_sensor  = VibrationSensor(sensor_configs["vibration"])

    _sim_step = [0]
    _sim_start_str = config["simulation"].get("simulation_start", "2026-03-10 22:00")
    _sim_start_dt  = datetime.strptime(_sim_start_str, "%Y-%m-%d %H:%M")

    # Sleep starts at 22:00 — minute 0 of the night
    _sleep_start_hour = 22

    def simulated_timestamp():
        vt = _sim_start_dt + timedelta(minutes=_sim_step[0])
        return vt.timestamp()

    for sensor in (temp_sensor, heart_rate_sensor, vibration_sensor, presence_sensor):
        sensor.timestamp_provider = simulated_timestamp

    # ── Actuators ─────────────────────────────────────────────────────────────
    l_cfg = actuators_config["light"]
    c_light = create_config(catalog_url, l_cfg["actuatorID"], l_cfg["name"], l_cfg["type"],
                            houseid, bedroomid, broker_ip, port,
                            topic_publish=l_cfg["topic_publish"], topic_subscribe=l_cfg["topic_subscribe"], is_sensor=False)

    h_cfg = actuators_config["heater"]
    c_heater = create_config(catalog_url, h_cfg["actuatorID"], h_cfg["name"], h_cfg["type"],
                             houseid, bedroomid, broker_ip, port,
                             topic_publish=h_cfg["topic_publish"], topic_subscribe=h_cfg["topic_subscribe"], is_sensor=False)

    f_cfg = actuators_config["fan"]
    c_fan = create_config(catalog_url, f_cfg["actuatorID"], f_cfg["name"], f_cfg["type"],
                          houseid, bedroomid, broker_ip, port,
                          topic_publish=f_cfg["topic_publish"], topic_subscribe=f_cfg["topic_subscribe"], is_sensor=False)

    fan_actuator    = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator  = LightActuator(c_light)

    for actuator in (fan_actuator, heater_actuator, light_actuator):
        actuator.timestamp_provider = simulated_timestamp

    light_actuator.value = 50
    light_actuator.publish_data(light_actuator.value, unit="%", name="LightLevel")

    mqtt_monitor = MQTTFeedbackMonitor(broker_ip, port, userid, houseid, bedroomid, initial_light=50)
    mqtt_monitor.start()

    try:
        time.sleep(2)

        sim_phases      = config["simulation_phases"]
        total_minutes   = sim_phases["total_minutes"]
        steps           = sim_phases["steps"]
        real_step_seconds = duration_seconds / steps

        def get_virtual_time(step):
            vt = _sim_start_dt + timedelta(minutes=step)
            return vt.hour, vt.minute, step

        def get_baseline_temp(minute):
            sleep_end_min = int(sim_phases["sleep_end"] * 60) - _sleep_start_hour * 60
            if minute <= sleep_end_min:
                return 23 - (5.0 / sleep_end_min) * minute
            morning_duration = total_minutes - sleep_end_min
            return 18 + (4.0 / morning_duration) * (minute - sleep_end_min)

        fan_cooling_per_min    = thermal_config["fan_cooling_per_min"]
        heater_warming_per_min = thermal_config["heater_warming_per_min"]
        ambient_pull_factor    = thermal_config["ambient_pull_factor"]
        min_temp               = thermal_config["min_temp"]
        max_temp               = thermal_config["max_temp"]
        current_temp           = thermal_config["starting_temp"]

        for step in range(steps):
            if stop_event.is_set():
                break

            _sim_step[0] = step
            hour, minute, virtual_minute = get_virtual_time(step)
            baseline_temp = get_baseline_temp(virtual_minute)

            fan_on    = getattr(fan_actuator,    'state', 'OFF') == "ON"
            heater_on = getattr(heater_actuator, 'state', 'OFF') == "ON"

            current_temp += (baseline_temp - current_temp) * ambient_pull_factor
            if fan_on:    current_temp -= fan_cooling_per_min
            if heater_on: current_temp += heater_warming_per_min
            current_temp = max(min_temp, min(max_temp, current_temp))

            sim_ts = simulated_timestamp()

            temp_sensor.value = current_temp
            temp_sensor.publish_data(round(current_temp, 2), unit="degC", timestamp=sim_ts)

            # ── Presence: in bed from 22:00 to 07:00 ─────────────────────────
            presence_value = 1 if (hour >= _sleep_start_hour or hour < 7) else 0
            presence_sensor.publish_data(presence_value, timestamp=sim_ts)

            # ── Sleep stage based on minutes elapsed since sleep start ──────
            # Compute how many minutes have passed since _sleep_start_hour
            # Works correctly across midnight (e.g. 22:00 → 00:00 → 07:00)
            vt = _sim_start_dt + timedelta(minutes=step)
            sleep_start_dt = vt.replace(hour=_sleep_start_hour, minute=0, second=0, microsecond=0)
            if vt < sleep_start_dt:
                sleep_start_dt -= timedelta(days=1)
            minute_of_night = int((vt - sleep_start_dt).total_seconds() / 60)

            if presence_value == 1:
                stage = get_sleep_stage(minute_of_night)
            else:
                stage = "AWAKE"

            # ── Heart rate and vibration driven by stage ───────────────────────
            heart_rate_value  = get_hr_for_stage(stage, step)
            vibration_value   = get_vibration_for_stage(stage, step)

            heart_rate_sensor.publish_data(round(heart_rate_value, 2), unit="bpm", timestamp=sim_ts)
            vibration_sensor.publish_data(round(vibration_value, 4), unit="g", timestamp=sim_ts)

            mqtt_states  = mqtt_monitor.get_states()
            light_mqtt   = mqtt_states.get("light", "?")
            heater_mqtt  = "ON" if mqtt_states.get("heater") == 1 else "OFF"
            fan_mqtt     = "ON" if mqtt_states.get("fan") == 1 else "OFF"
            phase        = mqtt_states.get("phase", "DAY")

            vt_str = (_sim_start_dt + timedelta(minutes=step)).strftime("%Y-%m-%d %H:%M")

            line = (f"[User {userid} | {vt_str}] Stage={stage:<5} "
                    f"Temp={current_temp:.2f}°C, Pres={presence_value}, "
                    f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.4f}g | "
                    f"Phase={phase} | MQTT[L={light_mqtt}, F={fan_mqtt}, H={heater_mqtt}]\n")

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
                logger.exception(f"Error stopping component for user {userid}: {e}")
        try:
            mqtt_monitor.stop()
        except Exception:
            logger.exception("Error stopping MQTT monitor")


def run_multi_user_simulation(duration_seconds=60):
    config = load_test_config()
    users_to_simulate = config.get("users", [config["simulation"]])
    print(f"--- Starting Multi-User Simulation ({len(users_to_simulate)} users) ---")

    stop_event = threading.Event()
    threads = []

    for user_info in users_to_simulate:
        t = threading.Thread(
            target=simulate_single_user,
            args=(user_info, config, duration_seconds, stop_event),
            name=f"Thread-User-{user_info['userid']}"
        )
        threads.append(t)
        t.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopping all simulations...")
        stop_event.set()
        for t in threads:
            t.join()
        print("All simulations stopped.")


if __name__ == "__main__":
    run_multi_user_simulation(duration_seconds=60)  # Run for 2 minutes (adjust as needed)