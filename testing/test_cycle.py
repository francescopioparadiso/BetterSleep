import json
import sys
import os
import time
import threading
import logging
from datetime import datetime

# Path setups
logging.basicConfig(filename='test_cycle.log', level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../sleep_cycle')))
from sleep_cycle.sleep_cycle_manager import SleepCycleManager
# Fixed imports including Actuators
from device_connector.Simulate_Sensor import *
from common.MQTT.MyMQTT import MyMQTT


def load_test_config(config_path="conf_test.json"):
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

        # State storage - initialize with default values
        self.actuator_states = {
            "light": initial_light,  # Initial light level
            "heater": "OFF",  # Default heater state
            "fan": "OFF"  # Default fan state
        }
        self.current_phase = "DAY"  # Default phase
        self.mqtt_client = None

    def on_message(self, topic, payload):
        """Handle incoming MQTT messages."""
        try:
            data = json.loads(payload)

            # Parse actuator feedback: House/{houseid}/Bedroom/{bedroomid}/actuator/{device}/data
            if "actuator" in topic and "data" in topic:
                parts = topic.split("/")
                if len(parts) >= 7:
                    device_type = parts[5]  # light, heater, fan
                    if 'e' in data and len(data['e']) > 0:
                        value = data['e'][0].get('v')
                        self.actuator_states[device_type] = value
                        logger.debug(f"Actuator {device_type} state updated: {value}")

            # Parse phase feedback: House/{houseid}/Bedroom/{bedroomid}/phase
            elif "phase" in topic and "actuator" not in topic:
                if 'e' in data and len(data['e']) > 0:
                    phase = data['e'][0].get('v')
                    self.current_phase = phase
                    logger.debug(f"Phase updated: {phase}")

        except Exception as e:
            logger.error(f"Error parsing MQTT message on topic {topic}: {e}")

    def start(self):
        """Start MQTT client to monitor feedback."""
        try:
            client_id = f"TestCycleMonitor_{self.userid}"
            self.mqtt_client = MyMQTT(client_id, self.broker, self.port, self)
            self.mqtt_client.start()

            # Subscribe to actuator data topics
            topics = [
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/light/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/heater/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/actuator/fan/data",
                f"House/{self.houseid}/Bedroom/{self.bedroomid}/phase"  # Phase topic
            ]

            for topic in topics:
                self.mqtt_client.mySubscribe(topic)
                logger.info(f"Subscribed to: {topic}")

        except Exception as e:
            logger.error(f"Error starting MQTT feedback monitor: {e}")

    def stop(self):
        """Stop MQTT client."""
        try:
            if self.mqtt_client:
                self.mqtt_client.stop()
        except Exception as e:
            logger.error(f"Error stopping MQTT feedback monitor: {e}")

    def notify(self, topic, payload):
        """Called by MyMQTT when a message is received."""
        self.on_message(topic, payload)

    def get_states(self):
        """Get current actuator states and phase."""
        return {
            "light": self.actuator_states.get("light", "?"),
            "heater": self.actuator_states.get("heater", "?"),
            "fan": self.actuator_states.get("fan", "?"),
            "phase": self.current_phase if self.current_phase else "DAY"
        }




def test_night_simulation(duration_seconds=60, presence_decider=None):
    """
    Simulates a complete night cycle from 21:00 to 08:00 (11 hours).

    This function creates a virtual environment where:
    - Time is accelerated (real seconds = virtual minutes)
    - Sensors publish fake data via MQTT to a broker
    - The sleep cycle manager (separate microservice) receives and processes data
    - Temperature is controlled by fan/heater actuators
    - Light brightness transitions smoothly during wind-down and wake-up

    Args:
        duration_seconds: Real-world duration of the simulation (default 60s = 1 minute)
        presence_decider: Optional callback for custom presence logic (unused currently)

    Phases simulated:
        21:00-21:30: Day phase (user awake)
        21:30-22:00: Wind-down phase (light dims, temp adjusts)
        22:00-07:00: Sleep phase (full night conditions)
        07:00-07:30: Wake-up phase (light brightens, temp adjusts)
        07:30-08:00: Day phase (user awake)
    """
    # Load configuration
    config = load_test_config()

    userid = config["simulation"]["userid"]
    houseid = config["simulation"]["houseid"]
    bedroomid = config["simulation"]["bedroomid"]

    # Extract configuration values
    catalog_url = config["catalog"]["url"]
    broker_ip = config["mqtt"]["broker"]
    port = config["mqtt"]["port"]

    sensors_config = config["sensors"]
    actuators_config = config["actuators"]
    thermal_config = config["thermal_dynamics"]

    logger.info(f"Starting test simulation for user {userid} in house {houseid}, bedroom {bedroomid}")
    logger.info(f"MQTT Broker: {broker_ip}:{port}")
    logger.info(f"Catalog URL: {catalog_url}")

    # Create sensor configurations from JSON
    sensor_configs = {}

    # Temperature sensor
    temp_config = sensors_config["temperature"]
    c_temp = create_config(
        catalog_url, temp_config["sensorID"], temp_config["name"], temp_config["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=temp_config["topic_publish"]
    )
    sensor_configs["temp"] = c_temp

    # Heart rate sensor
    hr_config = sensors_config["heart_rate"]
    c_heart_rate = create_config(
        catalog_url, hr_config["sensorID"], hr_config["name"], hr_config["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=hr_config["topic_publish"],
        topic_subscribe=hr_config["topic_subscribe"]
    )
    sensor_configs["hr"] = c_heart_rate

    # Presence sensor
    pres_config = sensors_config["presence"]
    c_pres = create_config(
        catalog_url, pres_config["sensorID"], pres_config["name"], pres_config["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=pres_config["topic_publish"]
    )
    sensor_configs["presence"] = c_pres

    # Vibration sensor
    vib_config = sensors_config["vibration"]
    c_vibration = create_config(
        catalog_url, vib_config["sensorID"], vib_config["name"], vib_config["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=vib_config["topic_publish"]
    )
    sensor_configs["vibration"] = c_vibration

    # Create sensor instances
    temp_sensor = TemperatureSensor(c_temp)
    heart_rate_sensor = HeartRateSensor(c_heart_rate)
    vibration_sensor = VibrationSensor(c_vibration)
    presence_sensor = PresenceSensor(c_pres)

    # current simulation step — updated each iteration before sensors publish
    _sim_step = [0]

    def simulated_timestamp():
        """
        Returns a Unix timestamp encoding the virtual HH:MM of the current
        simulation step. The PhaseManager decodes this to drive its clock,
        so it follows the test's virtual time instead of the system clock.
        """
        s = _sim_step[0]
        h = (21 + (s // 60)) % 24
        m = s % 60
        from datetime import datetime as _dt
        return _dt.now().replace(hour=h, minute=m, second=0, microsecond=0).timestamp()

    # Inject simulated timestamp provider into all sensors
    for sensor in (temp_sensor, heart_rate_sensor, vibration_sensor, presence_sensor):
        sensor.timestamp_provider = simulated_timestamp

    # Create actuator configurations from JSON
    actuator_configs = {}

    # Light actuator
    light_cfg = actuators_config["light"]
    c_light = create_config(
        catalog_url, light_cfg["actuatorID"], light_cfg["name"], light_cfg["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=light_cfg["topic_publish"],
        topic_subscribe=light_cfg["topic_subscribe"], is_sensor=False
    )
    actuator_configs["light"] = c_light

    # Heater actuator
    heater_cfg = actuators_config["heater"]
    c_heater = create_config(
        catalog_url, heater_cfg["actuatorID"], heater_cfg["name"], heater_cfg["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=heater_cfg["topic_publish"],
        topic_subscribe=heater_cfg["topic_subscribe"], is_sensor=False
    )
    actuator_configs["heater"] = c_heater

    # Fan actuator
    fan_cfg = actuators_config["fan"]
    c_fan = create_config(
        catalog_url, fan_cfg["actuatorID"], fan_cfg["name"], fan_cfg["type"],
        houseid, bedroomid, broker_ip, port, topic_publish=fan_cfg["topic_publish"],
        topic_subscribe=fan_cfg["topic_subscribe"], is_sensor=False
    )
    actuator_configs["fan"] = c_fan

    # Create actuator instances
    fan_actuator = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator = LightActuator(c_light)

    # Inject simulated timestamp provider into all actuators
    for actuator in (fan_actuator, heater_actuator, light_actuator):
        actuator.timestamp_provider = simulated_timestamp

    # Initialize light at 50% brightness and publish state
    light_actuator.value = 50
    light_actuator.publish_data(light_actuator.value, unit="%", name="LightLevel")

    # Initialize MQTT feedback monitor to receive actuator states from sleep_cycle_manager
    mqtt_monitor = MQTTFeedbackMonitor(broker_ip, port, userid, houseid, bedroomid, initial_light=50)
    mqtt_monitor.start()

    # Wait for MQTT connections to stabilize
    time.sleep(2)

    stop_event = threading.Event()

    # Simulation time configuration from config
    sim_phases = config["simulation_phases"]
    total_minutes = sim_phases["total_minutes"]
    steps = sim_phases["steps"]
    real_step_seconds = duration_seconds / steps  # Real time per simulated minute

    def get_virtual_time(step):
        """
        Convert simulation step to virtual clock time.

        Args:
            step: Current simulation step (0-659)

        Returns:
            tuple: (hour, minute, virtual_minute) where virtual_minute is total minutes elapsed
        """
        hour = (21 + (step // 60)) % 24
        minute = step % 60
        return hour, minute, step

    def get_baseline_temp(minute):
        """
        Calculate baseline room temperature without HVAC intervention.
        Simulates natural cooling during night and warming in morning.

        Args:
            minute: Virtual minutes elapsed since 21:00

        Returns:
            float: Target baseline temperature in °C
        """
        # Extract phase boundaries from config (in hours)
        sleep_end_hour = sim_phases["sleep_end"]
        wake_up_start_hour = sim_phases["wake_up_start"]

        # Convert hours to minutes
        sleep_end_min = int(sleep_end_hour * 60) - 21 * 60  # Adjust for start time 21:00
        wake_up_start_min = int(wake_up_start_hour * 60) - 21 * 60

        # Night cooling phase: 21:00-07:00 (600 minutes): 23°C -> 18°C
        if minute <= sleep_end_min:
            return 23 - (5.0 / sleep_end_min) * minute
        # Morning warming phase: 07:00-08:00 (60 minutes): 18°C -> 22°C
        morning_duration = total_minutes - sleep_end_min
        return 18 + (4.0 / morning_duration) * (minute - sleep_end_min)

    # Thermal dynamics configuration from config
    fan_cooling_per_min = thermal_config["fan_cooling_per_min"]
    heater_warming_per_min = thermal_config["heater_warming_per_min"]
    ambient_pull_factor = thermal_config["ambient_pull_factor"]
    min_temp = thermal_config["min_temp"]
    max_temp = thermal_config["max_temp"]
    current_temp = thermal_config["starting_temp"]

    def simulation_loop():
        """
        Main simulation loop that runs through the night cycle.

        Simulates:
        - Virtual time progression (21:00 -> 08:00)
        - Temperature dynamics with HVAC control
        - Sensor data publishing (temperature, presence, heart rate, vibration)
        - Actuator states (light, heater, fan)

        The sleep_cycle_manager (separate microservice) will:
        - Receive sensor data via MQTT
        - Publish actuator commands
        - Manage sleep phases
        """
        nonlocal current_temp
        print("--- Simulazione Notte Accelerata (Standalone) ---")
        print("Simulation period: 21:00 - 08:00 (11 hours)")
        print("Wind-down phase: 21:30 - 22:00 (30 minutes)")
        print("Night phase: 22:00 - 07:00 (9 hours)")
        print("Wake-up phase: 07:30 - 08:00 (30 minutes)")
        print()
        print("NOTE: sleep_cycle_manager is a separate microservice")
        print("      It will receive sensor data and publish actuator commands via MQTT")
        print()

        for step in range(steps):
            _sim_step[0] = step  # update virtual clock before sensors publish
            hour, minute, virtual_minute = get_virtual_time(step)

            # Calculate target temperature based on natural ambient conditions
            baseline_temp = get_baseline_temp(virtual_minute)

            # Check actuator states
            fan_on = getattr(fan_actuator, 'state', 'OFF') == "ON"
            heater_on = getattr(heater_actuator, 'state', 'OFF') == "ON"

            # Apply thermal dynamics:
            # 1. Natural drift toward baseline temperature
            current_temp += (baseline_temp - current_temp) * ambient_pull_factor
            # 2. Active cooling from fan
            if fan_on:
                current_temp -= fan_cooling_per_min
            # 3. Active heating from heater
            if heater_on:
                current_temp += heater_warming_per_min
            # 4. Enforce physical bounds
            current_temp = max(min_temp, min(max_temp, current_temp))

            # Get synchronized timestamp for all sensor readings
            sim_ts = simulated_timestamp()

            # Publish sensor data
            temp_sensor.value = current_temp

            temp_sensor.publish_data(round(current_temp, 2), unit="degC", timestamp=sim_ts)

            # Presence: 1 in bed (22:00-07:00), 0 out of bed
            presence_value = 1 if (hour >= 22 or hour < 7) else 0
            presence_sensor.publish_data(presence_value, timestamp=sim_ts)

            # Heart rate: baseline 60 bpm, +10 when present, with small oscillation
            heart_rate_value = 60 + (presence_value * 10) + (5 * (0.5 - (step % 10) / 10))
            heart_rate_sensor.publish_data(round(heart_rate_value, 2), unit="bpm", timestamp=sim_ts)

            # Vibration: 0.1 when present (movement), with small oscillation
            vibration_value = 0.1 * presence_value + 0.05 * (0.5 - (step % 20) / 20)
            vibration_sensor.publish_data(round(vibration_value, 3), unit="g", timestamp=sim_ts)

            # Get actuator states and phase from MQTT feedback (what sleep_cycle_manager is sending)
            mqtt_states = mqtt_monitor.get_states()
            light_mqtt = mqtt_states.get("light", "?")
            heater_mqtt = mqtt_states.get("heater", "?")
            fan_mqtt = mqtt_states.get("fan", "?")
            phase = mqtt_states.get("phase", "DAY")
            fan_mqtt="ON" if fan_mqtt == 1 else "OFF"
            heater_mqtt="ON" if heater_mqtt == 1 else "OFF"
            # Console output for monitoring
            print(f"[{hour:02d}:{minute:02d}] Temp={current_temp:.2f}°C, Presenza={presence_value}, "
                  f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.3f}g | "
                  f"Phase={phase} | MQTT[Light={light_mqtt}, Fan={fan_mqtt}, Heater={heater_mqtt}]")

            # Real-time delay between simulation steps
            time.sleep(real_step_seconds)

            if stop_event.is_set():
                break

    sim_thread = threading.Thread(target=simulation_loop)
    sim_thread.start()

    try:
        sim_thread.join()
    except KeyboardInterrupt:
        stop_event.set()
        sim_thread.join()
        print("Simulazione interrotta.")


if __name__ == "__main__":
    # Use dynamic night_time and morning_time from active_users_cache
    #save the log in a file and not send it to the console
    test_night_simulation(duration_seconds=60)
