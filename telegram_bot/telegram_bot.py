import json
import os
import logging
from datetime import datetime

import cherrypy
from dotenv import load_dotenv
import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardButton, InlineKeyboardMarkup

from catalog_client import CatalogClient

logger = logging.getLogger(__name__)


def _format_devices_message(devices, include_id=False, numbered=False, header=None):
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


def _parse_time(text: str):
    """Parse HH:MM or HH:MM:SS into HH:MM:SS string, or return None."""
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Default user-state structure
# ---------------------------------------------------------------------------
def _default_state() -> dict:
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


class TelegramBot:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog = CatalogClient(self.catalog_url, self.service_info, remove_interval=self.remove_interval)
        self.chatIDs = []
        self.user_states = {}

        load_dotenv()
        self.token = os.getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN not found in .env")

        self.bot = telepot.Bot(self.token)
        MessageLoop(self.bot, {
            'chat': self.on_chat_message,
            'callback_query': self.on_callback_query,
        }).run_as_thread()

        try:
            self.catalog.register_service()
        except Exception as e:
            logger.error(f'Failed to start catalog heartbeat: {e}')

    # -----------------------------------------------------------------------
    # State helpers
    # -----------------------------------------------------------------------

    def _ensure_user_state(self, chat_ID):
        if chat_ID not in self.user_states:
            self.user_states[chat_ID] = _default_state()

    def _get(self, chat_ID, key, default=None):
        """Get a top-level state field."""
        return self.user_states.get(chat_ID, {}).get(key, default)

    def _get_bedroom_info(self, chat_ID, key, default=None):
        """Get a field from the local bedroom_info cache."""
        return self._get(chat_ID, "bedroom_info", {}).get(key, default)

    def _set_state(self, chat_ID, state, **kwargs):
        """Update top-level state fields (state, username, bedroom_id, pending_device_type)."""
        entry = self.user_states.setdefault(chat_ID, _default_state())
        entry["state"] = state
        for k, v in kwargs.items():
            entry[k] = v

    def _set_bedroom_info(self, chat_ID, **kwargs):
        """Update bedroom_info fields."""
        self.user_states.setdefault(chat_ID, _default_state())["bedroom_info"].update(kwargs)

    def _reset_bedroom_info(self, chat_ID):
        """Clear all bedroom_info data."""
        self.user_states.setdefault(chat_ID, _default_state())["bedroom_info"] = _default_state()["bedroom_info"].copy()

    def _require_username(self, chat_ID):
        """Return username or send an error and return None."""
        username = self._get(chat_ID, "username")
        if not username:
            self.bot.sendMessage(chat_ID, "⚠️ You need to register first — please send /start to begin.")
        return username

    def _require_bedroom(self, chat_ID):
        """Return bedroom_id or send an error and return None."""
        bedroom_id = self._get(chat_ID, "bedroom_id")
        if not bedroom_id:
            self.bot.sendMessage(chat_ID, "🏠 You don't have a room yet. Use /start to create one.")
        return bedroom_id

    # -----------------------------------------------------------------------
    # Message routing
    # -----------------------------------------------------------------------

    def on_chat_message(self, msg):
        content_type, _, chat_ID = telepot.glance(msg)
        if content_type != 'text':
            return

        self._ensure_user_state(chat_ID)
        text = msg['text']

        if text == "/start":
            self._handle_start(chat_ID)
            return
        if text == "/help":
            self._handle_help(chat_ID)
            return

        state = self._get(chat_ID, "state")
        if state:
            self._dispatch_state(chat_ID, state, text)

    def _dispatch_state(self, chat_ID, state, message):
        handlers = {
            "waiting_username":             self._handle_waiting_username,
            "waiting_room_name":            self._handle_waiting_room_name,
            "waiting_room_bedtime":         self._handle_waiting_room_bedtime,
            "waiting_room_wakeup":          self._handle_waiting_room_wakeup,
            "waiting_room_temp":            self._handle_waiting_room_temp,
            "waiting_delete_confirmation":  self._handle_delete_room,
            "waiting_add_device_name":      self._handle_waiting_add_device_name,
            "waiting_remove_device_choice": self._handle_waiting_remove_device_choice,
        }
        handler = handlers.get(state)
        if handler:
            handler(chat_ID, message)

    def on_callback_query(self, msg):
        query_ID, from_ID, query_data = telepot.glance(msg, flavor='callback_query')
        self.bot.answerCallbackQuery(query_ID)
        self._ensure_user_state(from_ID)

        handlers = {
            "create_room":       self._cb_create_room,
            "view_data":         self._cb_view_data,
            "manage_settings":   self._cb_manage_settings,
            "manage_devices":    self._cb_manage_devices,
            "delete_room":       self._cb_delete_room,
            "view_sensor_data":  self._cb_view_sensor_data,
            "view_sleep_quality": self._cb_view_sleep_quality,
            "main_menu":         self._cb_main_menu,
            "remove_device":     self._cb_remove_device,
            "list_devices":      self._cb_list_devices,
            "add_device":        self._send_type_of_device_options,
            "add_device_light":  lambda cid: self._cb_add_device(cid, device_type="light"),
            "add_device_heater": lambda cid: self._cb_add_device(cid, device_type="heater"),
            "add_device_fan":    lambda cid: self._cb_add_device(cid, device_type="fan"),
        }

        handler = handlers.get(query_data)
        if handler:
            handler(from_ID)
        else:
            self.bot.sendMessage(from_ID, "❗ Unknown option or feature — not implemented yet.")

    # -----------------------------------------------------------------------
    # Callback handlers
    # -----------------------------------------------------------------------

    def _cb_create_room(self, chat_ID):
        if not self._require_username(chat_ID):
            return
        self._reset_bedroom_info(chat_ID)
        self.bot.sendMessage(chat_ID, "📝 Let's create a new room — what's the room name? (e.g. 'Bedroom')")
        self._set_state(chat_ID, "waiting_room_name")

    def _cb_view_data(self, chat_ID):
        self._send_room_data_options(chat_ID)

    def _cb_manage_settings(self, chat_ID):
        self._refresh_bedroom_info(chat_ID)
        room_name    = self._get_bedroom_info(chat_ID, "room_name")    or "N/A"
        bedtime      = self._get_bedroom_info(chat_ID, "bedtime")      or "N/A"
        wakeup       = self._get_bedroom_info(chat_ID, "wakeup")       or "N/A"
        desired_temp = self._get_bedroom_info(chat_ID, "desired_temp") or "N/A"
        self.bot.sendMessage(
            chat_ID,
            f"🏷️ Room: {room_name}\n"
            f"🛌 Bedtime: {bedtime}\n"
            f"⏰ Wakeup: {wakeup}\n"
            f"🌡️ Desired temperature: {desired_temp}°C"
        )
        self._send_room_settings_options(chat_ID)

    def _cb_manage_devices(self, chat_ID):
        self._send_device_management_options(chat_ID)

    def _cb_list_devices(self, chat_ID):
        self._show_devices(chat_ID)

    def _cb_delete_room(self, chat_ID):
        self.bot.sendMessage(chat_ID, "⚠️ Are you sure you want to delete the room? Type 'yes' to confirm. This action cannot be undone.")
        self._set_state(chat_ID, "waiting_delete_confirmation")

    def _cb_view_sensor_data(self, chat_ID):
        self.bot.sendMessage(chat_ID, "🔎 Sensor data — feature not implemented yet. We're working on it! 🚧")


    def _cb_view_sleep_quality(self, chat_ID):
        self.bot.sendMessage(chat_ID, "💤 Sleep quality — feature not implemented yet. Stay tuned! ✨")

    def _cb_main_menu(self, chat_ID):
        self._send_registered_user_options(chat_ID)

    def _cb_add_device(self, chat_ID, device_type=None):
        if device_type not in ("light", "heater", "fan"):
            self.bot.sendMessage(chat_ID, "❌ Unsupported device type.")
            return
        self._set_state(chat_ID, "waiting_add_device_name", pending_device_type=device_type)
        self.bot.sendMessage(chat_ID, f"➕ Great — what should we call the {device_type} device? Send a short name. 🏷️")

    def _cb_remove_device(self, chat_ID):
        self._begin_remove_device(chat_ID)

    # -----------------------------------------------------------------------
    # Keyboard Button options
    # -----------------------------------------------------------------------

    def _send_device_management_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 List devices",       callback_data="list_devices")],
            [InlineKeyboardButton(text="➕ Add device",          callback_data="add_device")],
            [InlineKeyboardButton(text="🗑️ Remove device",      callback_data="remove_device")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",  callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "🔧 Device management — choose an option:", reply_markup=keyboard)


    def _send_type_of_device_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💡 Light",   callback_data="add_device_light")],
            [InlineKeyboardButton(text="🌡️ Heater",  callback_data="add_device_heater")],
            [InlineKeyboardButton(text="❄️ Fan",     callback_data="add_device_fan")],
            [InlineKeyboardButton(text="⬅️ Back to device management", callback_data="manage_devices")],
        ])
        self.bot.sendMessage(chat_ID, "✨ Select the type of device to add:", reply_markup=keyboard)


    def _send_registered_user_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 View room data",       callback_data="view_data")],
            [InlineKeyboardButton(text="🔧 Manage devices",       callback_data="manage_devices")],
            [InlineKeyboardButton(text="⚙️ Manage room settings", callback_data="manage_settings")],
        ])
        self.bot.sendMessage(chat_ID, "Hi! What would you like to do next? 🌙", reply_markup=keyboard)


    def _send_room_settings_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Delete room",         callback_data="delete_room")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",   callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "Room settings — choose an option:", reply_markup=keyboard)


    def _send_room_data_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 View sensor data",    callback_data="view_sensor_data")],
            [InlineKeyboardButton(text="📉 View sleep quality",  callback_data="view_sleep_quality")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",  callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "Choose data to view:", reply_markup=keyboard)

    # -----------------------------------------------------------------------
    # State handlers
    # -----------------------------------------------------------------------

    def _handle_start(self, chat_ID):
        if chat_ID not in self.chatIDs:
            self.chatIDs.append(chat_ID)

        self._handle_restore_user_session(chat_ID)
        state = self._get(chat_ID, "state")

        if state == "registered":
            self._send_registered_user_options(chat_ID)
            return
        if state:
            return  # pending wizard state restored; do nothing

        # fresh user
        self.bot.sendMessage(chat_ID, "👋 Welcome to BetterSleep — your sleep-friendly assistant! Type /help for tips.")
        self.bot.sendMessage(chat_ID, "To get started, please choose a username:")
        self._set_state(chat_ID, "waiting_username", username=None)

    def _handle_help(self, chat_ID):
        self.bot.sendMessage(chat_ID, "🤖 Available commands:\n/start - Start the bot and register\n/help - Show this help message")

    def _handle_waiting_username(self, chat_ID, message):
        username = message.strip()
        if self._check_username_exists(chat_ID, username):
            self.bot.sendMessage(chat_ID, "❗ That username is already taken. Please choose a different one:")
            return

        payload = {"username": username, "telegram_chat_id": chat_ID, "bedroom_id": None}
        res = self.catalog.post("addUser", json=payload)
        if not res:
            self.bot.sendMessage(chat_ID, "❌ Could not create your account right now. Please try again later.")
            return

        self._set_state(chat_ID, "waiting_room_name", username=username)
        self.bot.sendMessage(chat_ID, f"🎉 Nice to meet you, {username}! Let's set up your personal room. What's the room name? Send 'skip' to use a default name.")

    def _handle_waiting_room_name(self, chat_ID, message):
        if not self._require_username(chat_ID):
            return

        room_name = message.strip()
        if room_name.lower() == 'skip' or room_name == '':
            room_name = f"{self._get(chat_ID, 'username')}'s room"

        # room_name is the single shared field — used both during wizard and in settings display
        self._set_bedroom_info(chat_ID, room_name=room_name)
        self._set_state(chat_ID, "waiting_room_bedtime")
        self.bot.sendMessage(chat_ID, "🕰️ What's your usual bedtime? Reply in HH:MM (24h), e.g. 23:00")

    def _handle_waiting_room_bedtime(self, chat_ID, message):
        bedtime = _parse_time(message)
        if not bedtime:
            self.bot.sendMessage(chat_ID, "❗ Invalid time format. Please use HH:MM, e.g. 23:00")
            return
        self._set_bedroom_info(chat_ID, bedtime=bedtime)
        self._set_state(chat_ID, "waiting_room_wakeup")
        self.bot.sendMessage(chat_ID, "⏰ Now send your usual wakeup time in HH:MM, e.g. 07:00")

    def _handle_waiting_room_wakeup(self, chat_ID, message):
        wakeup = _parse_time(message)
        if not wakeup:
            self.bot.sendMessage(chat_ID, "❗ Invalid time format. Please use HH:MM, e.g. 07:00")
            return
        self._set_bedroom_info(chat_ID, wakeup=wakeup)
        self._set_state(chat_ID, "waiting_room_temp")
        self.bot.sendMessage(chat_ID, "🌡️ Finally, what's your desired bedroom temperature? Send a number, e.g. 21.5")

    def _handle_waiting_room_temp(self, chat_ID, message):
        try:
            temp = float(message.strip())
        except ValueError:
            self.bot.sendMessage(chat_ID, "❗ Invalid temperature. Please send a number, e.g. 22 or 21.5")
            return
        if temp < 5 or temp > 35:
            self.bot.sendMessage(chat_ID, "⚠️ Please choose a temperature between 5 and 35 °C.")
            return

        self._set_bedroom_info(chat_ID, desired_temp=temp)

        # collect all bedroom_info fields and create the room
        room_name    = self._get_bedroom_info(chat_ID, "room_name")
        bedtime      = self._get_bedroom_info(chat_ID, "bedtime")
        wakeup       = self._get_bedroom_info(chat_ID, "wakeup")
        desired_temp = self._get_bedroom_info(chat_ID, "desired_temp")
        username     = self._get(chat_ID, "username")

        self.bot.sendMessage(
            chat_ID,
            f"🔨 Creating room '{room_name}' — bedtime {bedtime}, wakeup {wakeup}, temp {desired_temp}°C…"
        )
        room_id = self._create_bedroom(chat_ID, room_name, bedtime=bedtime, wakeup=wakeup, desired_temperature=desired_temp)

        if not room_id:
            self.bot.sendMessage(chat_ID, "❌ Couldn't create the room right now. Let's try again — what's the room name?")
            self._reset_bedroom_info(chat_ID)
            self._set_state(chat_ID, "waiting_room_name")
            return

        assoc_res = self.catalog.post("associateUserToBedroom", json={"telegram_chat_id": chat_ID, "bedroom_id": room_id})
        if assoc_res and assoc_res.get("status") == "success":
            self._finalize_registration(chat_ID, username, room_id)
        else:
            self.bot.sendMessage(chat_ID, "❌ Could not associate the room to your user. Please try again.")
            try:
                self.catalog.delete("removeRoom", params={"bedroom_id": room_id})
            except Exception:
                pass
            self._reset_bedroom_info(chat_ID)
            self._set_state(chat_ID, "waiting_room_name")

    def _handle_delete_room(self, chat_ID, message):
        if message.lower() != "yes":
            self.bot.sendMessage(chat_ID, "✅ Room deletion cancelled. No changes made.")
            self._send_registered_user_options(chat_ID)
            return

        bedroom_id = self._get(chat_ID, "bedroom_id")
        self._remove_bedroom(bedroom_id)
        self.bot.sendMessage(chat_ID, f"🗑️ Room {bedroom_id} deleted.")
        self._reset_bedroom_info(chat_ID)
        self._set_state(chat_ID, None, bedroom_id=None)
        self._reset_to_room_choice(chat_ID)

    def _handle_waiting_remove_device_choice(self, chat_ID, message):
        if not message.strip().isdigit():
            self.bot.sendMessage(chat_ID, "❗ Please send a valid number (e.g., 0, 1, 2).")
            return
        idx = int(message.strip())
        devices = self._get_bedroom_info(chat_ID, "devices_list") or []
        if idx < 0 or idx >= len(devices):
            self.bot.sendMessage(chat_ID, "❗ Number out of range. Please try again.")
            return

        device_id = devices[idx].get('device_id')
        res = self.catalog.delete("removeDevice", params={"deviceID": device_id})
        if res is not None:
            self.bot.sendMessage(chat_ID, f"✅ Device {device_id} removed.")
        else:
            self.bot.sendMessage(chat_ID, f"❌ Failed to remove device {device_id}.")

        self._set_bedroom_info(chat_ID, devices_list=None)
        self._reset_to_room_choice(chat_ID)

    def _handle_waiting_add_device_name(self, chat_ID, message):
        name = message.strip()
        if not name:
            self.bot.sendMessage(chat_ID, "❗ Please send a non-empty name for the device.")
            return
        if len(name) > 64:
            self.bot.sendMessage(chat_ID, "❗ Please choose a shorter name (max 64 characters).")
            return

        pending_type = self._get(chat_ID, "pending_device_type")
        if not pending_type:
            self.bot.sendMessage(chat_ID, "⚠️ Device type not selected. Please start again from Manage devices.")
            self._reset_to_room_choice(chat_ID)
            return

        bedroom_id = self._require_bedroom(chat_ID)
        if not bedroom_id:
            self._reset_to_room_choice(chat_ID)
            return

        payload = {
            "device_name": name,
            "device_type": pending_type,
            "bedroom_id":  bedroom_id,
            "value": 0,
        }
        self.bot.sendMessage(chat_ID, f"🔧 Creating {pending_type} device named '{name}'…")
        res = self.catalog.post("addDevice", json=payload)

        if res and res.get("status") == "success":
            device_id = res.get("device_id") or res.get("id") or "(unknown)"
            self.bot.sendMessage(chat_ID, f"✅ Device created: {name} (id: {device_id}) — added to your room.")
        else:
            err = res.get("error") if isinstance(res, dict) else None
            self.bot.sendMessage(chat_ID, f"❌ Could not create device{': ' + err if err else '.'}")

        self._set_state(chat_ID, self._get(chat_ID, "state"), pending_device_type=None)
        self._reset_to_room_choice(chat_ID)

    # -----------------------------------------------------------------------
    # Flow helpers
    # -----------------------------------------------------------------------

    def _reset_to_room_choice(self, chat_ID):
        username   = self._get(chat_ID, "username")
        bedroom_id = self._get(chat_ID, "bedroom_id")

        if username and bedroom_id:
            self._set_state(chat_ID, "registered")
            self._send_registered_user_options(chat_ID)
        elif username:
            self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You don't have a room yet. Let's create one! 🏠")
            self.bot.sendMessage(chat_ID, "What's the room name? Send 'skip' for the default.")
            self._reset_bedroom_info(chat_ID)
            self._set_state(chat_ID, "waiting_room_name")
        else:
            self._set_state(chat_ID, None)
            self.bot.sendMessage(chat_ID, "Please send /start to begin.")

    def _begin_remove_device(self, chat_ID):
        devices, error = self._get_devices_for_user(chat_ID)
        if error:
            self.bot.sendMessage(chat_ID, error)
            return
        self._set_bedroom_info(chat_ID, devices_list=devices)
        msg = _format_devices_message(devices, include_id=True, numbered=True, header="🗑️ Select the device to remove — send the number:")
        self.bot.sendMessage(chat_ID, msg)
        self._set_state(chat_ID, "waiting_remove_device_choice")

    def _finalize_registration(self, chat_ID, username, room_id, joined=False):
        greeting = "Good morning" if 6 <= datetime.now().hour < 18 else "Good evening"
        msg = (
            f"{greeting} ☀️, {username}! You have successfully joined room {room_id}."
            if joined else
            f"{greeting} 🌙, {username}! Your personal room {room_id} is ready. Happy sleeping! 🛌"
        )
        self.bot.sendMessage(chat_ID, msg)
        self._set_state(chat_ID, "registered", bedroom_id=room_id, username=username)
        self._send_registered_user_options(chat_ID)

    def _get_devices_for_user(self, chat_ID):
        """Fetch devices for the given user's bedroom. Returns (devices, error_str)."""
        bedroom_id = self._require_bedroom(chat_ID)
        if not bedroom_id:
            return None, None  # message already sent by _require_bedroom

        res = self.catalog.get("getDevices", params={"bedroom_id": bedroom_id})
        if not res or res.get("status") != "success":
            return None, "Could not retrieve devices."

        devices = res.get("devices", [])
        if not devices:
            return None, "No devices found in your room."

        return devices, None

    def _show_devices(self, chat_ID):
        """Fetch and display devices for the user's bedroom."""
        devices, error = self._get_devices_for_user(chat_ID)
        if error:
            self.bot.sendMessage(chat_ID, error)
            return
        msg = _format_devices_message(devices, include_id=False, numbered=False, header="🛋️ Devices in your room:")
        self.bot.sendMessage(chat_ID, msg)

    # -----------------------------------------------------------------------
    # Catalog HTTP calls
    # -----------------------------------------------------------------------

    def _create_bedroom(self, chat_ID, room_name, bedtime=None, wakeup=None, desired_temperature=None):
        payload = {
            "room_name":           room_name,
            "bedtime":             bedtime or "23:00:00",
            "wakeup":              wakeup  or "07:00:00",
            "desired_temperature": desired_temperature if desired_temperature is not None else 22.0,
        }
        data = self.catalog.post("addBedroom", json=payload)
        if data:
            room_id = data.get("bedroom_id")
            self.bot.sendMessage(chat_ID, f"✅ Room '{room_name}' created! ID: {room_id} — you're all set.")
            return room_id
        return None

    def _remove_bedroom(self, bedroom_id):
        res = self.catalog.delete("removeRoom", params={"bedroom_id": bedroom_id})
        if res is not None:
            return True
        logger.error(f"Error removing bedroom {bedroom_id}")
        return False

    def _check_username_exists(self, chat_ID, username):
        data = self.catalog.get("checkUsername", params={"username": username})
        if data and data.get("exists"):
            self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another.")
            return True
        return False

    def _refresh_bedroom_info(self, chat_ID):
        """Fetch bedroom info from catalog and update wizard fields in place."""
        bedroom_id = self._get(chat_ID, "bedroom_id")
        params = {"telegram_chat_id": chat_ID}
        if bedroom_id:
            params["bedroom_id"] = bedroom_id

        try:
            info = self.catalog.get("getBedroomInfo", params=params)
        except Exception as e:
            logger.error(f"Exception fetching bedroom info: {e}")
            info = None

        if info and info.get("status") == "success":
            self._set_bedroom_info(
                chat_ID,
                room_name=info.get("room_name"),
                bedtime=info.get("bedtime"),
                wakeup=info.get("wakeup"),
                desired_temp=info.get("desired_temperature"),
            )
            if info.get("bedroom_id"):
                self._set_state(chat_ID, self._get(chat_ID, "state"), bedroom_id=info["bedroom_id"])
        else:
            err = info.get('error') if isinstance(info, dict) else None
            logger.error(f"Error fetching bedroom info for {bedroom_id}: {err or 'no response'}")
            self.bot.sendMessage(chat_ID, "⚠️ Could not retrieve room information right now. Some details may be missing.")

    def _handle_restore_user_session(self, chat_ID):
        try:
            data = self.catalog.get("getUserSession", params={"telegram_chat_id": chat_ID})
            if not data:
                return

            username   = data.get("username")
            bedroom_id = data.get("bedroom_id")

            if username and bedroom_id:
                self._set_state(chat_ID, "registered", username=username, bedroom_id=bedroom_id)
                self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You're in room {bedroom_id}. 👋")
            elif username:
                self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You don't have a room yet. Let's create one! 🏠")
                self.bot.sendMessage(chat_ID, "What's the room name? Send 'skip' for the default.")
                self._set_state(chat_ID, "waiting_room_name", username=username)
        except Exception as e:
            logger.error(f"Unexpected error restoring session: {e}")
            self.bot.sendMessage(chat_ID, "⚠️ Unexpected error. Please try again.")


if __name__ == "__main__":
    with open("conf.json") as f:
        full_conf = json.load(f)

    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}
    bot = TelegramBot(full_conf)

    cherrypy.tree.mount(bot, '/', conf)
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port'],
    })

    cherrypy.engine.subscribe('start', bot.catalog.start_background_loop())
    cherrypy.engine.subscribe('stop',  bot.catalog.stop_background_loop())

    cherrypy.engine.start()
    cherrypy.engine.block()

