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
    def __init__(self, manager_instance, transition_window_min=30, check_interval=60, transition_curve_exponent=1.0):
        self.manager = manager_instance  # Reference to SleepCycleManager
        self.window = transition_window_min
        self.interval = check_interval
        self.transition_curve_exponent = float(transition_curve_exponent)
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_logic, daemon=True)
        self._thread.start()
        logger.info(f"PhaseManager started (Window: {self.window}m, Interval: {self.interval}s)")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run_logic(self):
        while not self._stop_event.is_set():
            try:
                self._check_all_rooms()
            except Exception as e:
                logger.error(f"Error in PhaseManager loop: {e}")
            self._stop_event.wait(self.interval)

    def _check_all_rooms(self):
        now = datetime.now()
        now_min = now.hour * 60 + now.minute

        for bedroom_id, room_prefs in self.manager.room_preferences_cache.items():
            user_id = room_prefs.get("userid")
            user_prefs = self.manager.user_preferences_cache.get(user_id)

            if not user_prefs or not room_prefs:
                continue

            night_min = _parse_to_min(user_prefs.get("night_time"))
            morn_min = _parse_to_min(user_prefs.get("morning_time"))
            if night_min is None or morn_min is None:
                continue

            wind_down_start = (night_min - self.window) % 1440
            wake_up_start = (morn_min - self.window) % 1440

            if _is_in_range(now_min, wind_down_start, night_min):
                progress = _get_progress(now_min, wind_down_start, night_min)
                self._apply_transition(bedroom_id, room_prefs, "WIND_DOWN", progress)
                continue

            if _is_in_range(now_min, wake_up_start, morn_min):
                progress = _get_progress(now_min, wake_up_start, morn_min)
                self._apply_transition(bedroom_id, room_prefs, "WAKE_UP", progress)
                continue

            if _is_in_range(now_min, night_min, morn_min):
                self._apply_static_phase(bedroom_id, room_prefs, "SLEEP")
            else:
                self._apply_static_phase(bedroom_id, room_prefs, "DAY")

    def _apply_static_phase(self, bedroom_id, room_prefs, phase):
        t_night = float(room_prefs.get("temperature_night", 18.0))
        t_morn = float(room_prefs.get("temperature_morning", 22.0))
        l_night = float(room_prefs.get("light_night", 0.0))
        l_morn = float(room_prefs.get("light_morning", 100.0))

        if phase == "SLEEP":
            target_t = t_night
            target_l = l_night
        else:
            target_t = t_morn
            target_l = l_morn

        self.manager.change_target_temperature_light(
            bedroom_id,
            target_temperature=target_t,
            target_light=target_l,
            phase=phase
        )

    def _curve_progress(self, progress):
        p = max(0.0, min(1.0, float(progress)))
        exponent = self.transition_curve_exponent
        return p ** exponent

    def _apply_transition(self, bedroom_id, room_prefs, phase, progress):
        t_night = float(room_prefs.get("temperature_night", 18.0))
        t_morn = float(room_prefs.get("temperature_morning", 22.0))
        l_night = float(room_prefs.get("light_night", 0.0))
        l_morn = float(room_prefs.get("light_morning", 100.0))

        curved_progress = self._curve_progress(progress)

        if phase == "WIND_DOWN":
            target_t = t_morn + (t_night - t_morn) * curved_progress
            target_l = l_morn + (l_night - l_morn) * curved_progress
        else:  # WAKE_UP
            target_t = t_night + (t_morn - t_night) * curved_progress
            target_l = l_night + (l_morn - l_night) * curved_progress

        self.manager.change_target_temperature_light(
            bedroom_id,
            target_temperature=target_t,
            target_light=target_l,
            phase=phase
        )
