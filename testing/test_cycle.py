import json
import sys
import os
import time
import threading


# Path setups
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../sleep_cycle')))

from sleep_cycle.sleep_cycle_manager import SleepCycleManager
# Fixed imports including Actuators
from device_connector.Simulate_Sensor import create_config , FanActuator, HeaterActuator, LightActuator, TemperatureSensor,PresenceSensor
def setup_manager():
    conf_path = "../sleep_cycle/conf.json"
    with open(conf_path, "r") as f:
        conf = json.load(f)
    return SleepCycleManager(conf, Debug=True)


def test_high_temp_simulation(duration_seconds=60):
    manager = setup_manager()
    userid = "1"
    houseid = "1"
    bedroomid = "1"


    # 2. Setup Ambient Temperature Sensor
    CATALOG_URL = "http://127.0.0.1:8080"
    BROKER_IP = "broker.hivemq.com"
    PORT = 1883
    PUB_TEMPLATE = f"House/{houseid}/Bedroom/{bedroomid}/sensor/ambient_temp/1/data"

    c_temp = create_config(
        CATALOG_URL, "1", "Temperature", "ambient_temp", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )
    temp_sensor = TemperatureSensor(c_temp)

    # Actuator configs using variables
    c_light = create_config(
        CATALOG_URL, "1", "Light", "light", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/light/command", is_sensor=False
    )
    c_heater = create_config(
        CATALOG_URL, "2", "Heater", "heater", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/heater/command", is_sensor=False
    )
    c_fan = create_config(
        CATALOG_URL, "3", "Fan", "fan", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/fan/command", is_sensor=False
    )
    fan_actuator = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator = LightActuator(c_light)

    # Device list for proper cleanup
    devices = [temp_sensor, fan_actuator, heater_actuator, light_actuator]

    # 3. Thread Management
    stop_event = threading.Event()

    def run_sensor():
        print(f"--- Sensor Thread Started: Simulating High Heat (29°C) ---")
        while not stop_event.is_set():
            # Simulate high ambient temperature (29°C) to trigger cooling
            temp_sensor.publish_data(29.0, unit="°C")
            time.sleep(10)  # Publish every 10 seconds

    def run_actuator(actuator, name):
        print(f"--- {name} Actuator Thread Started ---")
        while not stop_event.is_set():
            time.sleep(1)  # Actuators wait for commands

    # Start threads
    sensor_thread = threading.Thread(target=run_sensor)
    actuator_threads = [
        threading.Thread(target=run_actuator, args=(fan_actuator, "Fan")),
        threading.Thread(target=run_actuator, args=(heater_actuator, "Heater")),
        threading.Thread(target=run_actuator, args=(light_actuator, "Light")),
    ]
    sensor_thread.start()
    for t in actuator_threads:
        t.start()

    # 4. Run simulation for the specified duration
    try:
        time.sleep(duration_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        # 5. Clean Stop Logic
        print("\n--- Stopping Simulation ---")
        stop_event.set()  # Signal the thread to stop
        # Stop all devices (unregister from catalog, stop MQTT)
        for device in devices:
            device.stop()
        sensor_thread.join()  # Wait for thread to finish
        for t in actuator_threads:
            t.join()  # Wait for actuator threads to finish
        print("All threads joined. Simulation ended.")


def test_night_simulation(duration_seconds=300, presence_decider=None):
    manager = setup_manager()
    userid = "1"
    houseid = "1"
    bedroomid = "1"

    # Wait for active_users_cache to be populated
    time.sleep(2)
    user_data = manager.active_users_cache.get(userid)
    if user_data:
        night_time_str = user_data.get("night_time", "22:00")
        morning_time_str = user_data.get("morning_time", "07:00")
        try:
            night_hour = int(night_time_str.split(":")[0])
            morning_hour = int(morning_time_str.split(":")[0])
        except Exception:
            night_hour = 22
            morning_hour = 7
    else:
        night_hour = 22
        morning_hour = 7

    # 2. Setup Ambient Temperature Sensor
    CATALOG_URL = "http://127.0.0.1:8080"
    BROKER_IP = "broker.hivemq.com"
    PORT = 1883
    PUB_TEMPLATE = f"House/{houseid}/Bedroom/{bedroomid}/sensor/ambient_temp/1/data"

    c_temp = create_config(
        CATALOG_URL, "1", "Temperature", "ambient_temp", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )
    temp_sensor = TemperatureSensor(c_temp)

    # Presence sensor config (debug mode enabled)
    c_pres = create_config(
        CATALOG_URL, "1", "Presence", "presence", houseid, bedroomid, BROKER_IP, PORT, topic_publish=PUB_TEMPLATE
    )
    presence_sensor = PresenceSensor(c_pres, debug=True)

    # Actuator configs
    c_light = create_config(
        CATALOG_URL, "1", "Light", "light", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/light/command", is_sensor=False
    )
    c_heater = create_config(
        CATALOG_URL, "2", "Heater", "heater", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/heater/command", is_sensor=False
    )
    c_fan = create_config(
        CATALOG_URL, "3", "Fan", "fan", houseid, bedroomid, BROKER_IP, PORT,
        topic_subscribe=f"House/{houseid}/Bedroom/{bedroomid}/actuator/fan/command", is_sensor=False
    )
    fan_actuator = FanActuator(c_fan)
    heater_actuator = HeaterActuator(c_heater)
    light_actuator = LightActuator(c_light)

    devices = [temp_sensor, presence_sensor, fan_actuator, heater_actuator, light_actuator]

    stop_event = threading.Event()

    total_minutes = 480  # 8 hours
    fast_forward_interval = total_minutes // (duration_seconds // 5)

    def run_phase_and_presence():
        print("--- PhaseManager & Presence Sensor Thread Started ---")
        for step in range(duration_seconds // 5):
            manager.phase_manager.fast_forward(fast_forward_interval)
            current_time = manager.phase_manager.get_current_time()
            hour = current_time.hour
            # Decide presence value
            if presence_decider:
                if callable(presence_decider):
                    presence_value = presence_decider(step, hour, current_time)
                elif isinstance(presence_decider, (list, tuple)):
                    presence_value = presence_decider[step % len(presence_decider)]
                else:
                    presence_value = 1 if (night_hour <= hour or hour < morning_hour) else 0
            else:
                presence_value = 1 if (night_hour <= hour or hour < morning_hour) else 0
            print(f"[DEBUG] Step {step}: Simulated hour={hour}, presence={presence_value}, night_time={night_hour}, morning_time={morning_hour}")
            presence_sensor.publish_data(presence_value)
            time.sleep(5)
            if stop_event.is_set():
                break

    def run_sensor():
        print(f"--- Sensor Thread Started: Simulating High Heat (29°C) ---")
        while not stop_event.is_set():
            temp_sensor.publish_data(29.0, unit="°C")
            time.sleep(10)

    def run_actuator(actuator, name):
        print(f"--- {name} Actuator Thread Started ---")
        while not stop_event.is_set():
            time.sleep(1)

    phase_thread = threading.Thread(target=run_phase_and_presence)
    sensor_thread = threading.Thread(target=run_sensor)
    actuator_threads = [
        threading.Thread(target=run_actuator, args=(fan_actuator, "Fan")),
        threading.Thread(target=run_actuator, args=(heater_actuator, "Heater")),
        threading.Thread(target=run_actuator, args=(light_actuator, "Light")),
    ]
    phase_thread.start()
    sensor_thread.start()
    for t in actuator_threads:
        t.start()

    try:
        time.sleep(duration_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n--- Stopping Simulation ---")
        stop_event.set()
        for device in devices:
            device.stop()
        phase_thread.join()
        sensor_thread.join()
        for t in actuator_threads:
            t.join()
        print("All threads joined. Simulation ended.")


if __name__ == "__main__":
    # Use dynamic night_time and morning_time from active_users_cache
    test_night_simulation(duration_seconds=300)
