import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_to_min(val):
    try:
        parts = val.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return None


def _is_in_range(p, s, e):
    if s <= e:
        return s <= p < e
    return p >= s or p < e


def _get_progress(p, s, e):
    duration = (e - s) % 1440
    elapsed = (p - s) % 1440
    if duration == 0:
        return 1.0
    return max(0.0, min(1.0, elapsed / duration))


class PhaseManager:
    def __init__(self, manager_instance, transition_window_min=30, check_interval=60, transition_curve_exponent=1.0, prefer_fan=True):
        self.manager = manager_instance  # Reference to SleepCycleManager
        self.window = transition_window_min
        self.interval = check_interval
        self.transition_curve_exponent = float(transition_curve_exponent)
        self.prefer_fan = prefer_fan  # New flag: True=fan, False=heater
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """Start the background phase monitoring thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_logic, daemon=True)
        self._thread.start()
        logger.info(f"PhaseManager started (Window: {self.window}m, Interval: {self.interval}s)")

    def stop(self):
        """Stop the background phase monitoring thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run_logic(self):
        """Main loop that periodically checks all rooms for phase transitions."""
        while not self._stop_event.is_set():
            try:
                self._check_all_rooms()
            except Exception as e:
                logger.error(f"Error in PhaseManager loop: {e}")
            self._stop_event.wait(self.interval)

    def _check_all_rooms(self):
        now = self.get_current_time()
        now_min = now.hour * 60 + now.minute

        for userid, user_data in self.manager.active_users_cache.items():
            if not user_data:
                continue

            night_min = _parse_to_min(user_data.get("night_time"))
            morn_min = _parse_to_min(user_data.get("morning_time"))
            if night_min is None or morn_min is None:
                continue

            wind_down_start = (night_min - self.window) % 1440
            wake_up_start = (morn_min - self.window) % 1440

            if _is_in_range(now_min, wind_down_start, night_min):
                progress = _get_progress(now_min, wind_down_start, night_min)
                self._apply_transition(userid, user_data, "WIND_DOWN", progress)
                continue

            if _is_in_range(now_min, wake_up_start, morn_min):
                progress = _get_progress(now_min, wake_up_start, morn_min)
                self._apply_transition(userid, user_data, "WAKE_UP", progress)
                continue

            if _is_in_range(now_min, night_min, morn_min):
                self._apply_static_phase(userid, user_data, "SLEEP")
            else:
                self._apply_static_phase(userid, user_data, "DAY")

    def _apply_static_phase(self, userid, user_data, phase):
        t_night = float(user_data['config'].get("temperature_night", 18.0))
        t_morn = float(user_data['config'].get("temperature_morning", 22.0))
        l_night = float(user_data['config'].get("light_night", 0.0))

        if phase == "SLEEP":
            target_t = t_night
            # During sleep, enforce the night light level.
            target_l = l_night
        else:
            target_t = t_morn
            target_l = None

        # Clear the transition snapshot so the next transition captures a fresh value
        user_data.get("live_targets", {}).pop("transition_start_light", None)

        self.manager.change_target_temperature_light(
            userid,
            target_temperature=target_t,
            target_light=target_l,
            phase=phase
        )

    def _curve_progress(self, progress):
        p = max(0.0, min(1.0, float(progress)))
        exponent = self.transition_curve_exponent
        return p ** exponent

    def _apply_transition(self, userid, user_data, phase, progress):
        t_night = float(user_data['config'].get("temperature_night", 18.0))
        t_morn = float(user_data['config'].get("temperature_morning", 22.0))
        l_night = float(user_data['config'].get("light_night", 0.0))
        l_morn = float(user_data['config'].get("light_morning", 100.0))

        curved_progress = self._curve_progress(progress)
        live_targets = user_data.get("live_targets", {})
        live_values = user_data.get("live_values", {})

        # Capture the actual light value ONCE when the transition begins.
        # Priority: real sensor reading -> last target -> config fallback.
        if "transition_start_light" not in live_targets:
            current_light = live_values.get("light")  # Get actual sensor reading
            if current_light is None:
                current_light = live_targets.get("light")  # Fallback to last target

            if current_light is not None:
                live_targets["transition_start_light"] = max(0.0, min(100.0, float(current_light)))
            else:
                # Fallback: use config defaults if no actual value received yet
                live_targets["transition_start_light"] = l_morn if phase == "WIND_DOWN" else l_night

        start_l = live_targets["transition_start_light"]

        # Temperature always interpolates between config endpoints
        if phase == "WIND_DOWN":
            target_t = t_morn  # Maintain day temperature during wind-down
            end_l = l_night
        else:  # WAKE_UP
            target_t = t_morn  # Use morning temperature during wake-up (22°C)
            end_l = l_morn

        target_l = start_l + ((end_l - start_l) * curved_progress)

        logger.info(f"[{phase}] progress={progress:.3f}, curved={curved_progress:.3f}, "
                    f"light: {start_l:.0f} -> {target_l:.1f} -> {end_l:.0f}")

        self.manager.change_target_temperature_light(
            userid,
            target_temperature=target_t,
            target_light=target_l,
            phase=phase
        )

    def get_current_time(self):
        """Clock source, overridable by MockPhaseManager for deterministic tests."""
        return datetime.now()
