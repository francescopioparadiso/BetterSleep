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
def setup_manager():
    conf_path = "../sleep_cycle/conf.json"
    with open(conf_path, "r") as f:
        conf = json.load(f)
    return SleepCycleManager(conf, Debug=True,logger=logger)



def test_night_simulation(duration_seconds=600, presence_decider=None):
    """
    Simulates a complete night cycle from 21:00 to 08:00 (11 hours).

    This function creates a virtual environment where:
    - Time is accelerated (real seconds = virtual minutes)
    - Sensors publish fake data with simulated timestamps
    - The sleep cycle manager responds with phase transitions
    - Temperature is controlled by fan/heater actuators
    - Light brightness transitions smoothly during wind-down and wake-up

    Args:
        duration_seconds: Real-world duration of the simulation (default 600s = 10 minutes)
        presence_decider: Optional callback for custom presence logic (unused currently)

    Phases simulated:
        21:00-21:30: Day phase (user awake)
        21:30-22:00: Wind-down phase (light dims, temp adjusts)
        22:00-07:00: Sleep phase (full night conditions)
        07:00-07:30: Wake-up phase (light brightens, temp adjusts)
        07:30-08:00: Day phase (user awake)
    """
    manager = setup_manager()
    userid = "1"
    houseid = "1"
    bedroomid = "1"

    # Wait for active_users_cache to be populated
    time.sleep(2)

    # Sensor and actuator configuration
    # All devices communicate via MQTT broker and register with the catalog service
    CATALOG_URL = "http://127.0.0.1:8080"
    BROKER_IP = "broker.hivemq.com"
    PORT = 1883
    PUB_TEMPLATE = f"House/{houseid}/Bedroom/{bedroomid}/sensor/ambient_temp/1/data"

    # Temperature sensor: monitors room ambient temperature
    c_temp = create_config(
        CATALOG_URL, "1", "Temperature", "ambient_temp", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )

    # Heart rate sensor: monitors user's heart rate during sleep
    c_heart_rate = create_config(
        CATALOG_URL, "2", "HeartRate", "heart_rate", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/heart_rate"
    )

    # Presence sensor: detects if user is in bed (1) or out of bed (0)
    c_pres = create_config(
        CATALOG_URL, "1", "Presence", "presence", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )

    # Vibration sensor: detects movement/restlessness during sleep
    c_vibration = create_config(
        CATALOG_URL, "3", "Vibration", "vibration", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )

    # Create sensor instances
    temp_sensor = TemperatureSensor(c_temp)
    heart_rate_sensor = HeartRateSensor(c_heart_rate )
    vibration_sensor = VibrationSensor(c_vibration)
    presence_sensor = PresenceSensor(c_pres)

    def simulated_timestamp():
        """
        Provides simulated timestamps for sensor data.
        Returns virtual time from the mock phase manager's fake clock.
        """
        phase_manager = getattr(manager, "phase_manager", None)
        if phase_manager is not None and hasattr(phase_manager, "get_current_time"):
            return phase_manager.get_current_time().timestamp()
        return time.time()

    # Inject simulated timestamp provider into all sensors
    for sensor in (temp_sensor, heart_rate_sensor, vibration_sensor, presence_sensor):
        sensor.timestamp_provider = simulated_timestamp

    # Actuator configurations
    # Light actuator: controls bedroom brightness (0-100%)
    c_light = create_config(
        CATALOG_URL, "1", "Light", "light", houseid, bedroomid, BROKER_IP, PORT,
        topic_publish="House/{houseID}/Bedroom/{roomID}/sensor/light/{ActuatorID}/data",
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/light/command", is_sensor=False
    )

    # Heater actuator: warms the room when temperature is below target
    c_heater = create_config(
        CATALOG_URL, "2", "Heater", "heater", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/heater/command", is_sensor=False
    )

    # Fan actuator: cools the room when temperature is above target
    c_fan = create_config(
        CATALOG_URL, "3", "Fan", "fan", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/fan/command", is_sensor=False
    )

    # Create actuator instances
    fan_actuator = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator = LightActuator(c_light)

    # Initialize light at 50% brightness
    light_actuator.value = 50
    light_actuator._publish_state()


    stop_event = threading.Event()

    # Simulation time configuration: 21:00 (9 PM) to 08:00 (8 AM) = 11 hours = 660 minutes
    total_minutes = 660  # 11 ore virtuali (21:00 -> 08:00)
    steps = 660  # Each step = 1 simulated minute
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
        Simulates natural cooling during night (21:00-07:00) and warming in morning (07:00-08:00).

        Args:
            minute: Virtual minutes elapsed since 21:00

        Returns:
            float: Target baseline temperature in °C
        """
        # Night cooling phase: 21:00-07:00 (600 minutes): 23°C -> 18°C
        if minute <= 600:
            return 23 - (5.0 / 600) * minute
        # Morning warming phase: 07:00-08:00 (60 minutes): 18°C -> 22°C
        return 18 + (4.0 / 60) * (minute - 600)

    # Thermal dynamics configuration (per simulated minute)
    fan_cooling_per_min = 0.18      # Temperature decrease when fan is ON (°C/min)
    heater_warming_per_min = 0.20   # Temperature increase when heater is ON (°C/min)
    ambient_pull_factor = 0.06      # Natural drift toward baseline (0-1, higher = faster)
    min_temp, max_temp = 14.0, 30.0 # Physical temperature bounds
    current_temp = 23.0             # Starting temperature at 21:00

    def simulation_loop():
        """
        Main simulation loop that runs through the night cycle.

        Simulates:
        - Virtual time progression (21:00 -> 08:00)
        - Temperature dynamics with HVAC control
        - Sensor data publishing (temperature, presence, heart rate, vibration)
        - Phase transitions (WIND_DOWN -> SLEEP -> WAKE_UP)
        """
        nonlocal current_temp
        print("--- Simulazione Notte Accelerata ---")
        print("Simulation period: 21:00 - 08:00 (11 hours)")
        print("Wind-down phase: 21:30 - 22:00 (30 minutes)")
        print("Night phase: 22:00 - 07:00 (9 hours)")
        print("Wake-up phase: 07:30 - 08:00 (30 minutes)")
        print()

        # Initialize mock phase manager with fake time starting at 21:00
        if hasattr(manager, "phase_manager") and hasattr(manager.phase_manager, "fast_forward"):
            manager.phase_manager.stop()
            # Start simulation at 21:00 (1 hour before wind-down begins)
            manager.phase_manager.fake_time = datetime(2026, 3, 9, 21, 0)
        manager._fetch_and_cache_room_preference(userid)  # Ensure cache is populated with correct night/morning times
        for step in range(steps):
            # Advance virtual time by 1 minute
            if hasattr(manager, "phase_manager") and hasattr(manager.phase_manager, "fast_forward"):
                manager.phase_manager.fast_forward(1)
                manager.phase_manager._check_all_rooms()

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

            phase=manager.active_users_cache[userid]["live_targets"]["phase"]
            # Console output for monitoring
            print(f"[{hour:02d}:{minute:02d}] Temp={current_temp:.2f}°C, Presenza={presence_value}, "
                  f"Light={getattr(light_actuator, 'value', '?')}%, "
                  f"Fan={getattr(fan_actuator, 'state', '?')}, "
                  f"Heater={getattr(heater_actuator, 'state', '?')}, "
                  f"HR={heart_rate_value:.2f}bpm, Vib={vibration_value:.3f}g"
                  f", Phase={phase }")


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
