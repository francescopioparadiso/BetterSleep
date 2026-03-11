import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def _parse_to_min(val):
    """Convert a time value to total minutes since midnight.

    Accepts:
    - "HH:MM" or "HH:MM:SS" strings
    - datetime.time objects
    - datetime.datetime objects (uses .hour / .minute)
    """
    if val is None:
        return None
    try:
        # datetime.time or datetime.datetime
        if hasattr(val, 'hour') and hasattr(val, 'minute'):
            return int(val.hour) * 60 + int(val.minute)
        # string "HH:MM" or "HH:MM:SS"
        parts = str(val).split(":")
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
    def __init__(self, manager_instance, transition_window_min=30, check_interval=60,
                 transition_curve_exponent=1.0, prefer_fan=True):
        self.manager = manager_instance
        self.window = transition_window_min
        self.interval = check_interval
        self.transition_curve_exponent = float(transition_curve_exponent)
        self.prefer_fan = prefer_fan

        # Per-user clocks: each user's sensor drives only that user's phase check.
        # _sensor_time_per_user  : {userid -> datetime}
        # _last_synced_minute    : {userid -> int}  (HH*60+MM, -1 = never synced)
        self._sensor_time_per_user = {}
        self._last_synced_minute = {}



    def _run_logic(self):
        """Keep the thread alive; all phase checks are triggered by sync_from_sensor_time()."""
        self._stop_event.wait()

    def sync_from_sensor_time(self, unix_ts, userid):
        """
        Called on every incoming sensor message for a specific user.
        Updates that user's virtual clock and triggers a phase check only for
        that user, once per unique virtual minute.

        - In simulation: test sends virtual timestamps (e.g. 21:30) → each
          user's phase changes according to that user's simulated time,
          independently of other users.
        - In production: sensors send real UTC timestamps → each user is
          evaluated against their own sensor's reported time.
        """
        if userid is None:
            return
        try:
            vt = datetime.fromtimestamp(float(unix_ts))
            new_minute = vt.hour * 60 + vt.minute
            # Only process once per unique virtual minute per user
            if new_minute <= self._last_synced_minute.get(userid, -1):
                return
            self._sensor_time_per_user[userid] = vt.replace(second=0, microsecond=0)
            self._last_synced_minute[userid] = new_minute
            logger.info(f"[PhaseManager] user={userid} clock → {self._sensor_time_per_user[userid].strftime('%H:%M')}")
            self._check_user(userid)
        except Exception as e:
            logger.error(f"PhaseManager sync_from_sensor_time error (user={userid}): {e}")

    def get_current_time(self, userid=None):
        """Returns the last sensor-reported time for a specific user (or None)."""
        if userid is not None:
            return self._sensor_time_per_user.get(userid)
        # Legacy fallback: return the most recently updated time across all users
        if not self._sensor_time_per_user:
            return None
        return max(self._sensor_time_per_user.values())

    def _check_user(self, userid):
        """Evaluate and apply the correct phase for a single user based on their own clock."""
        now = self._sensor_time_per_user.get(userid)
        if now is None:
            return

        now_min = now.hour * 60 + now.minute

        user_data = self.manager.active_users_cache.get(userid)
        if not user_data:
            logger.warning(f"[PhaseManager] user={userid} not in active_users_cache — skipping")
            return

        night_min = _parse_to_min(user_data.get("night_time"))
        morn_min  = _parse_to_min(user_data.get("morning_time"))

        logger.info(
            f"[PhaseManager] CHECK user={userid} | virtual_time={now.strftime('%H:%M')} ({now_min}m) | "
            f"night_time={user_data.get('night_time')!r} ({night_min}) | "
            f"morning_time={user_data.get('morning_time')!r} ({morn_min}) | "
            f"window={self.window}m"
        )

        if night_min is None or morn_min is None:
            logger.warning(
                f"[PhaseManager] user={userid}: night_time or morning_time missing or unparseable "
                f"(night_time={user_data.get('night_time')!r}, morning_time={user_data.get('morning_time')!r}) — skipping"
            )
            return

        wind_down_start = (night_min - self.window) % 1440
        wake_up_start   = (morn_min  - self.window) % 1440

        logger.info(
            f"[PhaseManager] user={userid} | wind_down_start={wind_down_start} | night={night_min} | "
            f"wake_up_start={wake_up_start} | morning={morn_min}"
        )

        if wind_down_start <= now_min < night_min:
            logger.info(f"[PhaseManager] user={userid} → WIND_DOWN (late sensor, robust)")
            progress = _get_progress(now_min, wind_down_start, night_min)
            self._apply_transition(userid, user_data, "WIND_DOWN", progress)
            return

        # SLEEP phase: start if now_min >= night_min or now_min < morn_min
        if (night_min <= now_min < 1440) or (now_min < morn_min):
            logger.info(f"[PhaseManager] user={userid} → SLEEP (robust phase check)")
            self._apply_static_phase(userid, user_data, "SLEEP")
            return

        # WAKE_UP phase: unchanged
        if wake_up_start <= now_min < morn_min:
            progress = _get_progress(now_min, wake_up_start, morn_min)
            logger.info(f"[PhaseManager] user={userid} → WAKE_UP (progress={progress:.3f})")
            self._apply_transition(userid, user_data, "WAKE_UP", progress)
            return

        # DAY phase: fallback
        logger.info(f"[PhaseManager] user={userid} → DAY")
        self._apply_static_phase(userid, user_data, "DAY")

    def _apply_static_phase(self, userid, user_data, phase):
        t_night = float(user_data['config'].get("temperature_night", 18.0))
        t_morn = float(user_data['config'].get("temperature_morning", 22.0))
        l_night = float(user_data['config'].get("light_night", 0.0))
        l_morn = float(user_data['config'].get("light_morning", 100.0))

        if phase == "SLEEP":
            target_t, target_l = t_night, l_night
        else:  # DAY
            target_t, target_l = t_morn, l_morn

        user_data.get("live_targets", {}).pop("transition_start_light", None)
        self.manager.change_target_temperature_light(
            userid, target_temperature=target_t, target_light=target_l, phase=phase)

    def _curve_progress(self, progress):
        return max(0.0, min(1.0, float(progress))) ** self.transition_curve_exponent

    def _apply_transition(self, userid, user_data, phase, progress):
        t_night = float(user_data['config'].get("temperature_night", 18.0))
        t_morn = float(user_data['config'].get("temperature_morning", 22.0))
        l_night = float(user_data['config'].get("light_night", 0.0))
        l_morn = float(user_data['config'].get("light_morning", 100.0))

        curved_progress = self._curve_progress(progress)
        live_targets = user_data.get("live_targets", {})
        live_values = user_data.get("live_values", {})

        if "transition_start_light" not in live_targets:
            # Explicit None check — 0.0 is a valid light value, must not be treated as missing
            current_light = live_values.get("light")
            if current_light is None:
                current_light = live_targets.get("light")
            if current_light is not None:
                live_targets["transition_start_light"] = max(0.0, min(100.0, float(current_light)))
            else:
                # No sensor or target reading yet — use config defaults
                live_targets["transition_start_light"] = l_morn if phase == "WIND_DOWN" else l_night

        start_l = live_targets["transition_start_light"]

        if phase == "WIND_DOWN":
            target_t = t_morn
            end_l = l_night
        else:  # WAKE_UP
            target_t = t_morn
            end_l = l_morn

        target_l = start_l + ((end_l - start_l) * curved_progress)

        logger.info(f"[{phase}] progress={progress:.3f}, curved={curved_progress:.3f}, "
                    f"light: {start_l:.0f} → {target_l:.1f} → {end_l:.0f}")

        self.manager.change_target_temperature_light(
            userid, target_temperature=target_t, target_light=target_l, phase=phase)
