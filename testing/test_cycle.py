import json
import sys
import os
import time
import threading
import logging
from datetime import datetime, timedelta

# Path setups - Add parent directory to Python path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(filename='test_cycle.log', level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# from sleep_cycle_manager.sleep_cycle_manager import SleepCycleManager
from device_connector.Simulate_Sensor import *
from common.MQTT.MyMQTT import MyMQTT


class MQTTCommandPublisher:
    """Publish START_SLEEP and FINISH_SLEEP commands for bed analytics."""

    def __init__(self, broker, port):
        self.client = MyMQTT(f"TestCyclePublisher_{int(time.time())}", broker, port, self)

    def notify(self, topic, payload):
        return None

    def start(self):
        self.client.start()

    def stop(self):
        self.client.stop()

    def publish(self, topic, payload):
        self.client.myPublish(topic, payload)

def load_test_config(config_path="conf.json"):
    """Load test cycle configuration from JSON file."""
    with open(config_path, "r") as f:
        return json.load(f)


class MQTTFeedbackMonitor:
    """Monitor MQTT feedback from actuators and sleep_cycle_manager."""

    def __init__(self, broker, port, userid, houseid, bedroomid, initial_light=50):
        self.broker = broker
        self.port = port
        self.userid = userid
        self.houseid = houseid
        self.bedroomid = bedroomid

        self.actuator_states = {
            "light": initial_light,
            "heater": "OFF",
            "fan": "OFF"
        }
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
                        logger.debug(f"[User {self.userid}] Actuator {device_type} state updated: {value}")

            elif "phase" in topic and "actuator" not in topic:
                if 'e' in data and len(data['e']) > 0:
                    phase = data['e'][0].get('v')
                    self.current_phase = phase
                    logger.debug(f"[User {self.userid}] Phase updated: {phase}")

        except Exception as e:
            logger.error(f"Error parsing MQTT message on topic {topic}: {e}")

    def start(self):
        try:
            # Ensure unique MQTT client ID per user monitor
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
    """Encapsulated simulation logic for a single user thread."""
    userid = user_info["userid"]
    houseid = user_info["houseid"]
    bedroomid = user_info["bedroomid"]

    catalog_url = config["catalog"]["url"]
    broker_ip = config["mqtt"]["broker"]
    port = config["mqtt"]["port"]

    sensors_config = config["sensors"]
    actuators_config = config["actuators"]
    thermal_config = config["thermal_dynamics"]
    filepath=f"SimulationStats_User{userid}.txt"
    logger.info(f"Starting test simulation for user {userid} in house {houseid}, bedroom {bedroomid}")
    with open(filepath, "w") as f:
        f.write(f"Simulation Stats for User {userid} | House {houseid} Bedroom {bedroomid}\n")

    command_publisher = MQTTCommandPublisher(broker_ip, port)
    command_publisher.start()
    sleep_topic_base = f"BedAnalitics/userid/{userid}/Bedroom/{bedroomid}"

    # Helper function to ensure unique sensor/actuator IDs across multiple users
    def make_unique_id(base_id):
        return f"{base_id}_{userid}"

    # Setup Sensors (using unique IDs)

    sensor_configs = {}

    t_cfg = sensors_config["temperature"]
    sensor_configs["temp"] = create_config(catalog_url, make_unique_id(t_cfg["sensorID"]), t_cfg["name"], t_cfg["type"],
                                           houseid, bedroomid, broker_ip, port, topic_publish=t_cfg["topic_publish"])

    hr_cfg = sensors_config["heart_rate"]
    sensor_configs["hr"] = create_config(catalog_url, make_unique_id(hr_cfg["sensorID"]), hr_cfg["name"],
                                         hr_cfg["type"], houseid, bedroomid, broker_ip, port,
                                         topic_publish=hr_cfg["topic_publish"],
                                         topic_subscribe=hr_cfg["topic_subscribe"])

    p_cfg = sensors_config["presence"]
    sensor_configs["presence"] = create_config(catalog_url, make_unique_id(p_cfg["sensorID"]), p_cfg["name"],
                                               p_cfg["type"], houseid, bedroomid, broker_ip, port,
                                               topic_publish=p_cfg["topic_publish"])

    v_cfg = sensors_config["vibration"]
    sensor_configs["vibration"] = create_config(catalog_url, make_unique_id(v_cfg["sensorID"]), v_cfg["name"],
                                                v_cfg["type"], houseid, bedroomid, broker_ip, port,
                                                topic_publish=v_cfg["topic_publish"])

    temp_sensor = TemperatureSensor(sensor_configs["temp"])
    heart_rate_sensor = HeartRateSensor(sensor_configs["hr"])
    presence_sensor = PresenceSensor(sensor_configs["presence"])
    vibration_sensor = VibrationSensor(sensor_configs["vibration"])

    _sim_step = [0]
    _sim_start_str = config["simulation"].get("simulation_start", "2026-03-10 21:00")
    _sim_start_dt = datetime.strptime(_sim_start_str, "%Y-%m-%d %H:%M")

    def simulated_timestamp():
        vt = _sim_start_dt + timedelta(minutes=_sim_step[0])
        return vt.timestamp()

    for sensor in (temp_sensor, heart_rate_sensor, vibration_sensor, presence_sensor):
        sensor.timestamp_provider = simulated_timestamp

    # Setup Actuators
    l_cfg = actuators_config["light"]
    c_light = create_config(catalog_url, make_unique_id(l_cfg["actuatorID"]), l_cfg["name"], l_cfg["type"], houseid,
                            bedroomid, broker_ip, port, topic_publish=l_cfg["topic_publish"],
                            topic_subscribe=l_cfg["topic_subscribe"], is_sensor=False)

    h_cfg = actuators_config["heater"]
    c_heater = create_config(catalog_url, make_unique_id(h_cfg["actuatorID"]), h_cfg["name"], h_cfg["type"], houseid,
                             bedroomid, broker_ip, port, topic_publish=h_cfg["topic_publish"],
                             topic_subscribe=h_cfg["topic_subscribe"], is_sensor=False)

    f_cfg = actuators_config["fan"]
    c_fan = create_config(catalog_url, make_unique_id(f_cfg["actuatorID"]), f_cfg["name"], f_cfg["type"], houseid,
                          bedroomid, broker_ip, port, topic_publish=f_cfg["topic_publish"],
                          topic_subscribe=f_cfg["topic_subscribe"], is_sensor=False)

    fan_actuator = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator = LightActuator(c_light)

    for actuator in (fan_actuator, heater_actuator, light_actuator):
        actuator.timestamp_provider = simulated_timestamp

    # Start values
    light_actuator.value = 50
    light_actuator.publish_data(light_actuator.value, unit="%", name="LightLevel")

    mqtt_monitor = MQTTFeedbackMonitor(broker_ip, port, userid, houseid, bedroomid, initial_light=50)
    mqtt_monitor.start()

    # Ensure sensors/actuators are stopped when simulation ends or interrupted
    try:
        time.sleep(2)

        start_ts = int(simulated_timestamp())
        command_publisher.publish(
            f"{sleep_topic_base}/StartSleep",
            {"action": "START_SLEEP", "timestamp": start_ts}
        )
        logger.info(f"Published START_SLEEP for user {userid} at {start_ts}")

        sim_phases = config["simulation_phases"]
        total_minutes = sim_phases["total_minutes"]
        steps = sim_phases["steps"]
        real_step_seconds = duration_seconds / steps

        def get_virtual_time(step):
            vt = _sim_start_dt + timedelta(minutes=step)
            return vt.hour, vt.minute, step

        def get_baseline_temp(minute):
            sleep_end_min = int(sim_phases["sleep_end"] * 60) - 21 * 60
            if minute <= sleep_end_min:
                return 23 - (5.0 / sleep_end_min) * minute
            morning_duration = total_minutes - sleep_end_min
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
            if fan_on: current_temp -= fan_cooling_per_min
            if heater_on: current_temp += heater_warming_per_min
            current_temp = max(min_temp, min(max_temp, current_temp))

            sim_ts = simulated_timestamp()

            temp_sensor.value = current_temp
            temp_sensor.publish_data(round(current_temp, 2), unit="degC", timestamp=sim_ts)

            presence_value = 1 if (hour >= 22 or hour < 7) else 0
            presence_sensor.publish_data(presence_value, timestamp=sim_ts)
            vibration_value = 0.005 * presence_value + 0.003 * (0.5 - (step % 20) / 20)
            heart_rate_value = 58 + (presence_value * 7) + (3 * (0.5 - (step % 10) / 10))
            heart_rate_sensor.publish_data(round(heart_rate_value, 2), unit="bpm", timestamp=sim_ts)
            vibration_sensor.publish_data(round(vibration_value, 3), unit="g", timestamp=sim_ts)

            mqtt_states = mqtt_monitor.get_states()
            light_mqtt = mqtt_states.get("light", "?")
            heater_mqtt = "ON" if mqtt_states.get("heater") == 1 else "OFF"
            fan_mqtt = "ON" if mqtt_states.get("fan") == 1 else "OFF"
            phase = mqtt_states.get("phase", "DAY")

            vt_str = (_sim_start_dt + timedelta(minutes=step)).strftime("%Y-%m-%d %H:%M")

            # Prefixed output with UserID so console logs are readable
            print(f"[User {userid} | {vt_str}] Temp={current_temp:.2f}°C, Pres={presence_value}, "
                  f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.3f}g | "
                  f"Phase={phase} | MQTT[L={light_mqtt}, F={fan_mqtt}, H={heater_mqtt}]")
            with open(filepath, "a") as f:
                f.write(f"[User {userid} | {vt_str}] Temp={current_temp:.2f}°C, Pres={presence_value}, "
                  f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.3f}g | "
                  f"Phase={phase} | MQTT[L={light_mqtt}, F={fan_mqtt}, H={heater_mqtt}]")
            time.sleep(real_step_seconds)

        if not stop_event.is_set():
            finish_ts = int(simulated_timestamp())
            command_publisher.publish(
                f"{sleep_topic_base}/FinishSleep",
                {"action": "FINISH_SLEEP", "timestamp": finish_ts}
            )
            logger.info(f"Published FINISH_SLEEP for user {userid} at {finish_ts}")

    finally:
        # Stop sensors and actuators (if they implement stop)
        for comp in (temp_sensor, heart_rate_sensor, presence_sensor, vibration_sensor,
                     fan_actuator, heater_actuator, light_actuator):
            try:
                if hasattr(comp, 'stop') and callable(getattr(comp, 'stop')):
                    comp.stop()
            except Exception as e:
                logger.exception(f"Error stopping component for user {userid}: {e}")

        # Ensure MQTT monitor stopped
        try:
            mqtt_monitor.stop()
        except Exception:
            logger.exception("Error stopping MQTT monitor")

        try:
            command_publisher.stop()
        except Exception:
            logger.exception("Error stopping MQTT command publisher")


def run_multi_user_simulation(duration_seconds=60):
    config = load_test_config()

    # We now expect a list of users in the config, or we generate one dynamically.
    # For backward compatibility, if only one user is in "simulation", we wrap it in a list.
    users_to_simulate = config.get("users", [config["simulation"]])

    print(f"--- Starting Multi-User Simulation ({len(users_to_simulate)} users) ---")

    stop_event = threading.Event()
    threads = []

    # Spawn a thread for each user
    for user_info in users_to_simulate:
        t = threading.Thread(
            target=simulate_single_user,
            args=(user_info, config, duration_seconds, stop_event),
            name=f"Thread-User-{user_info['userid']}"
        )
        threads.append(t)
        t.start()

    try:
        # Keep main thread alive while children run
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopping all simulations...")
        stop_event.set()
        for t in threads:
            t.join()


        print("All simulations stopped.")


if __name__ == "__main__":
    run_multi_user_simulation(duration_seconds=60)

