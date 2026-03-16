import logging
from datetime import datetime


def _parse_to_min(val):
    if val is None:
        return None
    try:
        if hasattr(val, 'hour') and hasattr(val, 'minute'):
            return int(val.hour) * 60 + int(val.minute)
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
    elapsed  = (p - s) % 1440
    if duration == 0:
        return 1.0
    return max(0.0, min(1.0, elapsed / duration))


class PhaseManager:
    def __init__(self, manager_instance, transition_window_min=30,
                 transition_curve_exponent=1.0, prefer_fan=True):
        self.manager = manager_instance
        self.logger  = manager_instance.logger
        self.window  = transition_window_min
        self.transition_curve_exponent = float(transition_curve_exponent)
        self.prefer_fan = prefer_fan
        self._sensor_time_per_user = {}

    def sync_from_sensor_time(self, unix_ts, userid):
        if userid is None:
            return
        try:
            vt = datetime.fromtimestamp(float(unix_ts)).replace(second=0, microsecond=0)
            if self._sensor_time_per_user.get(userid) == vt:
                return
            self._sensor_time_per_user[userid] = vt
            self._check_user(userid)
        except Exception as e:
            self.logger.error(f"PhaseManager sync error (user={userid}): {e}")

    def _check_user(self, userid):
        now = self._sensor_time_per_user.get(userid)
        if now is None:
            return

        now_min   = now.hour * 60 + now.minute
        user_data = self.manager.active_users_cache.get(userid)
        if not user_data:
            self.logger.warning(f"[PhaseManager] user={userid} not in active_users_cache — skipping")
            return

        night_min = _parse_to_min(user_data.get("night_time"))
        morn_min  = _parse_to_min(user_data.get("morning_time"))
        if night_min is None or morn_min is None:
            self.logger.warning(f"[PhaseManager] user={userid}: night_time or morning_time missing — skipping")
            return

        wind_down_start = (night_min - self.window) % 1440
        wake_up_start   = (morn_min  - self.window) % 1440

        if _is_in_range(now_min, wind_down_start, night_min):
            progress = _get_progress(now_min, wind_down_start, night_min)
            self._apply_transition(userid, user_data, "WIND_DOWN", progress)
        elif _is_in_range(now_min, wake_up_start, morn_min):
            progress = _get_progress(now_min, wake_up_start, morn_min)
            self._apply_transition(userid, user_data, "WAKE_UP", progress)
        elif _is_in_range(now_min, night_min, morn_min):
            self._apply_static_phase(userid, user_data, "SLEEP")
        else:
            self._apply_static_phase(userid, user_data, "DAY")

    def _get_user_config(self, user_data):
        cfg = user_data['config']
        return {
            "t_night": float(cfg.get("temperature_night",   18.0)),
            "t_morn":  float(cfg.get("temperature_morning", 22.0)),
            "l_night": float(cfg.get("light_night",          0.0)),
            "l_morn":  float(cfg.get("light_morning",       100.0)),
        }

    def _apply_static_phase(self, userid, user_data, phase):
        c = self._get_user_config(user_data)
        if phase == "SLEEP":
            target_t, target_l = c["t_night"], c["l_night"]
        else:
            target_t, target_l = c["t_morn"],  c["l_morn"]

        user_data.get("live_targets", {}).pop("transition_start_light", None)
        self.manager.change_target_temperature_light(
            userid, target_temperature=target_t, target_light=target_l, phase=phase
        )

    def _curve_progress(self, progress):
        return max(0.0, min(1.0, float(progress))) ** self.transition_curve_exponent

    def _apply_transition(self, userid, user_data, phase, progress):
        c = self._get_user_config(user_data)
        curved_progress = self._curve_progress(progress)
        live_targets    = user_data.get("live_targets", {})
        live_values     = user_data.get("live_values",  {})

        if "transition_start_light" not in live_targets:
            current_light = live_values.get("light") or live_targets.get("light")
            live_targets["transition_start_light"] = (
                max(0.0, min(100.0, float(current_light))) if current_light is not None
                else (c["l_morn"] if phase == "WIND_DOWN" else c["l_night"])
            )

        start_l  = live_targets["transition_start_light"]
        target_t = c["t_night"] if phase == "WIND_DOWN" else c["t_morn"]
        end_l    = c["l_night"] if phase == "WIND_DOWN" else c["l_morn"]
        target_l = start_l + (end_l - start_l) * curved_progress

        self.logger.info(
            f"[{phase}] user={userid} progress={progress:.3f} curved={curved_progress:.3f} "
            f"light: {start_l:.0f} → {target_l:.1f} → {end_l:.0f}"
        )

        self.manager.change_target_temperature_light(
            userid, target_temperature=target_t, target_light=target_l, phase=phase
        )