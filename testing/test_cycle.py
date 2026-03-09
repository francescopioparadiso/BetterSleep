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
from device_connector.Simulate_Sensor import create_config , FanActuator, HeaterActuator, LightActuator, TemperatureSensor,PresenceSensor
def setup_manager():
    conf_path = "../sleep_cycle/conf.json"
    with open(conf_path, "r") as f:
        conf = json.load(f)
    return SleepCycleManager(conf, Debug=True,logger=logger)



def test_night_simulation(duration_seconds=600, presence_decider=None):
    manager = setup_manager()
    userid = "1"
    houseid = "1"
    bedroomid = "1"

    # Wait for active_users_cache to be populated
    time.sleep(2)

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
        topic_publish="House/{houseID}/Bedroom/{roomID}/sensor/light/{ActuatorID}/data",
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
    light_actuator.value = 100
    light_actuator._publish_state()

    devices = [temp_sensor, presence_sensor, fan_actuator, heater_actuator, light_actuator]

    stop_event = threading.Event()

    total_minutes = 600  # 10 ore virtuali
    steps = 600  # Each step = 1 simulated minute
    real_step_seconds = duration_seconds / steps  # 600/600 = 1 second per simulated minute

    def get_virtual_time(step):
        hour = (21 + (step // 60)) % 24
        minute = step % 60
        return hour, minute, step

    def get_night_temp(minute):
        if minute <= 420:
            return 23 - (4.0 / 420) * minute
        else:
            return 18 + (4.0 / 180) * (minute - 420)

    def simulation_loop():
        print("--- Simulazione Notte Accelerata ---")
        print("Wind-down phase: 21:30 - 22:00 (30 minutes)")
        print("Night phase: 22:00 - 07:00")
        print("Wake-up phase: 06:30 - 07:00 (30 minutes)")
        print()
        # In debug mode use deterministic virtual-time checks (1 loop step = 1 minute).
        if hasattr(manager, "phase_manager") and hasattr(manager.phase_manager, "fast_forward"):
            manager.phase_manager.stop()
            # Start at 21:00 — wind-down begins at 21:30 (30 min before night_time)
            manager.phase_manager.fake_time = datetime(2026, 3, 9, 21, 0)

        for step in range(steps):
            if hasattr(manager, "phase_manager") and hasattr(manager.phase_manager, "fast_forward"):
                manager.phase_manager.fast_forward(1)
                manager.phase_manager._check_all_rooms()

            hour, minute, virtual_minute = get_virtual_time(step)
            temp = get_night_temp(virtual_minute)
            temp_sensor.value = temp
            temp_sensor.publish_data(temp, unit="°C")
            presence_value = 1 if (hour >= 22 or hour < 7) else 0
            presence_sensor.publish_data(presence_value)
            print(f"[{hour:02d}:{minute:02d}] Temp={temp:.2f}degC, Presenza={presence_value}, Light={getattr(light_actuator, 'value', '?')}, Fan={getattr(fan_actuator, 'state', '?')}, Heater={getattr(heater_actuator, 'state', '?')}")
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
    test_night_simulation(duration_seconds=600)
