import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def format_devices_message(devices, include_id=False, numbered=False, header=None):
    """Return a message string listing devices."""
    if not devices:
        return "No devices found. 🤷‍♀️"

    lines = []
    if header:
        lines.append(header)

    for i, d in enumerate(devices):
        device_name = d.get('device_name', 'Unnamed device')
        device_type = d.get('device_type')
        emoji = "💡" if device_type == "light" else ("🌡️" if device_type == "heater" else "❄️")
        line = f"{emoji} {device_name}"
        if include_id:
            line += f" (id: {d.get('device_id')})"
        if numbered:
            line = f"{i}: {line}"
        lines.append(line)

    return "\n".join(lines)


def parse_time(text: str):
    """Parse HH:MM or HH:MM:SS into HH:MM:SS string, or return None."""
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    return None


def default_state() -> dict:
    return {
        # --- persistent ---
        "state":               None,
        "username":            None,
        "bedroom_id":          None,
        "pending_device_type": None,
        "bedroom_info": {
            "room_name":    None,
            "bedtime":      None,
            "wakeup":       None,
            "desired_temp": None,
            "devices_list": None,
        },
    }

