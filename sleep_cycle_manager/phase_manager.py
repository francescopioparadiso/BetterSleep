from datetime import datetime


def _parse_to_min(val):
    if val is None:
        return None
    try:
        parts = str(val).split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None


def _is_in_range(p, s, e):
    if s <= e:
        return s <= p < e
    return p >= s or p < e


def _get_progress(current_min, start_min, end_min):
    duration = (end_min - start_min) % 1440
    elapsed  = (current_min - start_min) % 1440
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
        self._sensor_time_per_user = {} # userid → datetime of last sensor time update (rounded to minute)

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

        now_min = now.hour * 60 + now.minute

        entry = self.manager.user_cache.get(userid)
        if not entry:
            self.logger.warning(f"[PhaseManager] user={userid} not in cache — skipping")
            return

        night_min = _parse_to_min(entry.night_time)
        morn_min  = _parse_to_min(entry.morning_time)
        if night_min is None or morn_min is None:
            self.logger.warning(f"[PhaseManager] user={userid}: night_time or morning_time missing — skipping")
            return

        wind_down_start = (night_min - self.window) % 1440 #1440 is the number of minutes in a day
        wake_up_start   = (morn_min  - self.window) % 1440

        if _is_in_range(now_min, wind_down_start, night_min):
            progress = _get_progress(now_min, wind_down_start, night_min)
            self._apply_transition(userid, entry, "WIND_DOWN", progress)
        elif _is_in_range(now_min, wake_up_start, morn_min):
            progress = _get_progress(now_min, wake_up_start, morn_min)
            self._apply_transition(userid, entry, "WAKE_UP", progress)
        elif _is_in_range(now_min, night_min, morn_min):
            self._apply_static_phase(userid, entry, "SLEEP")
        else:
            self._apply_static_phase(userid, entry, "DAY")

    def _apply_static_phase(self, userid, entry, phase):
        entry.live_targets.pop("transition_start_light", None)

        if phase == "SLEEP":
            target_t = entry.config["temperature_night"]
            target_l = entry.config["light_night"]
        else:
            target_t = entry.config["temperature_morning"]
            target_l = entry.config["light_morning"]

        self.manager.change_target_temperature_light(
            userid, target_temperature=target_t, target_light=target_l, phase=phase
        )

    def _apply_transition(self, userid, entry, phase, progress):
        curved_progress = self._curve_progress(progress)

        if "transition_start_light" not in entry.live_targets:
            current_light = entry.actuators_state.get("light") or entry.live_targets.get("light")
            if current_light is not None:
                anchor = max(0.0, min(100.0, float(current_light)))
            else:
                anchor = (
                    entry.config["light_morning"] if phase == "WIND_DOWN"
                    else entry.config["light_night"]
                )
            entry.live_targets["transition_start_light"] = anchor

        start_l  = entry.live_targets["transition_start_light"]
        target_t = entry.config["temperature_night"]  if phase == "WIND_DOWN" else entry.config["temperature_morning"]
        end_l    = entry.config["light_night"]         if phase == "WIND_DOWN" else entry.config["light_morning"]
        target_l = start_l + (end_l - start_l) * curved_progress

        self.logger.info(
            f"[{phase}] user={userid} progress={progress:.3f} curved={curved_progress:.3f} "
            f"light: {start_l:.0f} → {target_l:.1f} → {end_l:.0f}"
        )

        self.manager.change_target_temperature_light(
            userid, target_temperature=target_t, target_light=target_l, phase=phase
        )

    def _curve_progress(self, progress):
        return max(0.0, min(1.0, float(progress))) ** self.transition_curve_exponent