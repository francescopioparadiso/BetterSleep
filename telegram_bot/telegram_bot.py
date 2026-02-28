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
from callback_handlers import CallbackHandlers
from state_handlers import StateHandlers

from utils import format_devices_message, default_state

logger = logging.getLogger(__name__)



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

        # instantiate handlers and pass self so handlers can call back into TelegramBot
        self.state_handlers = StateHandlers(self)
        self.callback_handlers = CallbackHandlers(self)

        MessageLoop(self.bot, {
            'chat': self.on_chat_message,
            'callback_query': self.on_callback_query,
        }).run_as_thread()

        try:
            self.catalog.register_service()
        except Exception as e:
            logger.error(f'Failed to start catalog heartbeat: {e}')

    # -----------------------------------------------------------------------
    # State helpers (public API for handlers)
    # -----------------------------------------------------------------------

    def _ensure_user_state(self, chat_ID):
        """Internal helper: ensure user state exists."""
        if chat_ID not in self.user_states:
            self.user_states[chat_ID] = default_state()

    def get(self, chat_ID, key, default=None):
        """Get a top-level state field."""
        return self.user_states.get(chat_ID, {}).get(key, default)

    def get_bedroom_info(self, chat_ID, key, default=None):
        """Get a field from the local bedroom_info cache."""
        return self.get(chat_ID, "bedroom_info", {}).get(key, default)

    def set_state(self, chat_ID, state, **kwargs):
        """Update top-level state fields (state, username, bedroom_id, pending_device_type)."""
        entry = self.user_states.setdefault(chat_ID, default_state())
        entry["state"] = state
        for k, v in kwargs.items():
            entry[k] = v

    def set_bedroom_info(self, chat_ID, **kwargs):
        """Update bedroom_info fields."""
        self.user_states.setdefault(chat_ID, default_state())["bedroom_info"].update(kwargs)

    def reset_bedroom_info(self, chat_ID):
        """Clear all bedroom_info data."""
        self.user_states.setdefault(chat_ID, default_state())["bedroom_info"] = default_state()["bedroom_info"].copy()

    def require_username(self, chat_ID):
        """Return username or send an error and return None."""
        username = self.get(chat_ID, "username")
        if not username:
            self.bot.sendMessage(chat_ID, "⚠️ You need to register first — please send /start to begin.")
        return username

    def require_bedroom(self, chat_ID):
        """Return bedroom_id or send an error and return None."""
        bedroom_id = self.get(chat_ID, "bedroom_id")
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
            return self.state_handlers.handle_start(chat_ID)
        if text == "/help":
            return self.state_handlers.handle_help(chat_ID)

        state = self.get(chat_ID, "state")
        if state:
            self._dispatch_state(chat_ID, state, text)

    def _dispatch_state(self, chat_ID, state, message):
        handlers = {
            "waiting_username":             self.state_handlers.handle_waiting_username,
            "waiting_room_name":            self.state_handlers.handle_waiting_room_name,
            "waiting_room_bedtime":         self.state_handlers.handle_waiting_room_bedtime,
            "waiting_room_wakeup":          self.state_handlers.handle_waiting_room_wakeup,
            "waiting_room_temp":            self.state_handlers.handle_waiting_room_temp,
            "waiting_delete_confirmation":  self.state_handlers.handle_delete_room,
            "waiting_add_device_name":      self.state_handlers.handle_waiting_add_device_name,
            "waiting_remove_device_choice": self.state_handlers.handle_waiting_remove_device_choice,
            "waiting_change_room_name":     self.state_handlers.handle_waiting_change_room_name,
            "waiting_change_bedtime":       self.state_handlers.handle_waiting_change_bedtime,
            "waiting_change_wakeup":        self.state_handlers.handle_waiting_change_wakeup,
            "waiting_change_temp":          self.state_handlers.handle_waiting_change_temp,
        }
        handler = handlers.get(state)
        if handler:
            handler(chat_ID, message)

    def on_callback_query(self, msg):
        query_ID, from_ID, query_data = telepot.glance(msg, flavor='callback_query')
        self.bot.answerCallbackQuery(query_ID)
        self._ensure_user_state(from_ID)

        handlers = {
            "create_room":       self.callback_handlers.handle_create_room,
            "view_data":         self.callback_handlers.handle_view_data,
            "manage_settings":   self.callback_handlers.handle_manage_settings,
            "manage_devices":    self.callback_handlers.handle_manage_devices,
            "delete_room":       self.callback_handlers.handle_delete_room,
            "view_sensor_data":  self.callback_handlers.handle_view_sensor_data,
            "view_sleep_quality": self.callback_handlers.handle_view_sleep_quality,
            "main_menu":         self.callback_handlers.handle_main_menu,
            "remove_device":     self.callback_handlers.handle_remove_device,
            "list_devices":      self.callback_handlers.handle_list_devices,
            "add_device":        self.send_type_of_device_options,
            "add_device_light":  lambda cid: self.callback_handlers.handle_add_device(cid, device_type="light"),
            "add_device_heater": lambda cid: self.callback_handlers.handle_add_device(cid, device_type="heater"),
            "add_device_fan":    lambda cid: self.callback_handlers.handle_add_device(cid, device_type="fan"),
            "change_room_name":  self.callback_handlers.handle_change_room_name,
            "change_bedtime":    self.callback_handlers.handle_change_bedtime,
            "change_wakeup":     self.callback_handlers.handle_change_wakeup,
            "change_temp":       self.callback_handlers.handle_change_temp,
        }

        handler = handlers.get(query_data)
        if handler:
            handler(from_ID)
        else:
            self.bot.sendMessage(from_ID, "❗ Unknown option or feature — not implemented yet.")

    # -----------------------------------------------------------------------
    # NOTE: callback-specific wrapper methods have been removed from this class.
    # All callback actions are delegated directly to `self.callback_handlers`.
    # -----------------------------------------------------------------------

    # -----------------------------------------------------------------------
    # Keyboard Button options (public API for handlers)
    # -----------------------------------------------------------------------

    def send_device_management_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 List devices",       callback_data="list_devices")],
            [InlineKeyboardButton(text="➕ Add device",          callback_data="add_device")],
            [InlineKeyboardButton(text="🗑️ Remove device",      callback_data="remove_device")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",  callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "🔧 Device management — choose an option:", reply_markup=keyboard)

    def send_type_of_device_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💡 Light",   callback_data="add_device_light")],
            [InlineKeyboardButton(text="🌡️ Heater",  callback_data="add_device_heater")],
            [InlineKeyboardButton(text="❄️ Fan",     callback_data="add_device_fan")],
            [InlineKeyboardButton(text="⬅️ Back to device management", callback_data="manage_devices")],
        ])
        self.bot.sendMessage(chat_ID, "✨ Select the type of device to add:", reply_markup=keyboard)

    def send_registered_user_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 View room data",       callback_data="view_data")],
            [InlineKeyboardButton(text="🔧 Manage devices",       callback_data="manage_devices")],
            [InlineKeyboardButton(text="⚙️ Manage room settings", callback_data="manage_settings")],
        ])
        self.bot.sendMessage(chat_ID, "Hi! What would you like to do next? 🌙", reply_markup=keyboard)

    def send_room_settings_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Delete room",         callback_data="delete_room")],
            [InlineKeyboardButton(text="⚙️ Change room name",   callback_data="change_room_name")],
            [InlineKeyboardButton(text="⏰ Change bedtime",      callback_data="change_bedtime")],
            [InlineKeyboardButton(text="⏰ Change wake-up time", callback_data="change_wakeup")],
            [InlineKeyboardButton(text="🌡️ Change desired temp", callback_data="change_temp")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",   callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "Room settings — choose an option:", reply_markup=keyboard)

    def send_room_data_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈 View sensor data",    callback_data="view_sensor_data")],
            [InlineKeyboardButton(text="📉 View sleep quality",  callback_data="view_sleep_quality")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",  callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "Choose data to view:", reply_markup=keyboard)

    # -----------------------------------------------------------------------
    # Flow helpers (public API for handlers)
    # -----------------------------------------------------------------------

    def ensure_valid_state_and_show_menu(self, chat_ID):

        # First, try to restore session from catalog if we don't have local data
        username   = self.get(chat_ID, "username")
        bedroom_id = self.get(chat_ID, "bedroom_id")

        # If we're missing data locally, try to restore from catalog (silently)
        if not username or not bedroom_id:
            self.restore_user_session(chat_ID, silent=True)
            # Re-read after restore attempt
            username   = self.get(chat_ID, "username")
            bedroom_id = self.get(chat_ID, "bedroom_id")

        if username and bedroom_id:
            # User is fully registered with a room
            self.set_state(chat_ID, "registered")
            self.send_registered_user_options(chat_ID)
        elif username:
            # User registered but no room yet - start room creation
            self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You don't have a room yet. Let's create one! 🏠")
            self.bot.sendMessage(chat_ID, "What's the room name? Send 'skip' for the default.")
            self.reset_bedroom_info(chat_ID)
            self.set_state(chat_ID, "waiting_room_name")
        else:
            self.set_state(chat_ID, None)
            self.bot.sendMessage(chat_ID, "Please send /start to begin.")

    def begin_remove_device(self, chat_ID):
        devices, error = self.get_devices_for_user(chat_ID)
        if error:
            self.bot.sendMessage(chat_ID, error)
            return
        self.set_bedroom_info(chat_ID, devices_list=devices)
        msg = format_devices_message(devices, include_id=True, numbered=True, header="🗑️ Select the device to remove — send the number:")
        self.bot.sendMessage(chat_ID, msg)
        self.set_state(chat_ID, "waiting_remove_device_choice")

    def finalize_registration(self, chat_ID, username, room_id, joined=False):
        greeting = "Good morning" if 6 <= datetime.now().hour < 18 else "Good evening"
        msg = (
            f"{greeting} ☀️, {username}! You have successfully joined room {room_id}."
            if joined else
            f"{greeting} 🌙, {username}! Your personal room {room_id} is ready. Happy sleeping! 🛌"
        )
        self.bot.sendMessage(chat_ID, msg)
        self.set_state(chat_ID, "registered", bedroom_id=room_id, username=username)
        self.send_registered_user_options(chat_ID)

    def get_devices_for_user(self, chat_ID):
        """Fetch devices for the given user's bedroom. Returns (devices, error_str)."""
        bedroom_id = self.require_bedroom(chat_ID)
        if not bedroom_id:
            return None, None  # message already sent by require_bedroom

        data, status, error = self.catalog.get("getDevices", params={"bedroom_id": bedroom_id})

        if error:
            if status == 404:
                return None, "❌ Bedroom not found."
            return None, f"❌ Could not retrieve devices: {error}"

        if not data or data.get("status") != "success":
            return None, "Could not retrieve devices."

        devices = data.get("devices", [])
        if not devices:
            return None, "No devices found in your room."

        return devices, None

    def show_devices(self, chat_ID):
        """Fetch and display devices for the user's bedroom."""
        devices, error = self.get_devices_for_user(chat_ID)
        if error:
            self.bot.sendMessage(chat_ID, error)
            return
        msg = format_devices_message(devices, include_id=False, numbered=False, header="🛋️ Devices in your room:")
        self.bot.sendMessage(chat_ID, msg)

    # -----------------------------------------------------------------------
    # Catalog HTTP calls (public API for handlers)
    # -----------------------------------------------------------------------

    def create_bedroom(self, chat_ID, room_name, bedtime=None, wakeup=None, desired_temperature=None):
        payload = {
            "room_name":           room_name,
            "bedtime":             bedtime or "23:00:00",
            "wakeup":              wakeup  or "07:00:00",
            "desired_temperature": desired_temperature if desired_temperature is not None else 22.0,
        }
        data, status, error = self.catalog.post("addBedroom", json=payload)
        if error:
            self.bot.sendMessage(chat_ID, f"❌ Could not create bedroom: {error}")
            return None
        if data:
            room_id = data.get("bedroom_id")
            self.bot.sendMessage(chat_ID, f"✅ Room '{room_name}' created! ID: {room_id} — you're all set.")
            return room_id
        return None

    def remove_bedroom(self, bedroom_id):
        data, status, error = self.catalog.delete("removeRoom", params={"bedroom_id": bedroom_id})
        if error:
            logger.error(f"Error removing bedroom {bedroom_id} ({status}): {error}")
            return False
        return True

    def check_username_exists(self, chat_ID, username):
        data, status, error = self.catalog.get("checkUsername", params={"username": username})
        if error:
            logger.error(f"Error checking username ({status}): {error}")
            return False
        if data and data.get("exists"):
            self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another.")
            return True
        return False

    def refresh_bedroom_info(self, chat_ID):
        """Fetch bedroom info from catalog and update wizard fields in place."""
        bedroom_id = self.get(chat_ID, "bedroom_id")
        params = {"telegram_chat_id": chat_ID}
        if bedroom_id:
            params["bedroom_id"] = bedroom_id

        info, status, error = self.catalog.get("getBedroomInfo", params=params)

        if error:
            logger.error(f"Error fetching bedroom info for {bedroom_id} ({status}): {error}")
            if status == 404:
                self.bot.sendMessage(chat_ID, "❌ Room not found. It may have been deleted.")
            else:
                self.bot.sendMessage(chat_ID, "⚠️ Could not retrieve room information right now. Some details may be missing.")
            return

        if info and info.get("status") == "success":
            self.set_bedroom_info(
                chat_ID,
                room_name=info.get("room_name"),
                bedtime=info.get("bedtime"),
                wakeup=info.get("wakeup"),
                desired_temp=info.get("desired_temperature"),
            )
            if info.get("bedroom_id"):
                self.set_state(chat_ID, self.get(chat_ID, "state"), bedroom_id=info["bedroom_id"])
        else:
            logger.error(f"Error fetching bedroom info for {bedroom_id}: invalid response")
            self.bot.sendMessage(chat_ID, "⚠️ Could not retrieve room information right now. Some details may be missing.")

    def restore_user_session(self, chat_ID, silent=False):
        """
        Restore user session from catalog.

        Args:
            chat_ID: The Telegram chat ID
            silent: If True, only restore data without sending welcome messages
        """
        data, status, error = self.catalog.get("getUserSession", params={"telegram_chat_id": chat_ID})

        if error:
            if status == 404:
                logger.debug(f"No session found for chat_id {chat_ID}")
            else:
                logger.error(f"Error restoring session ({status}): {error}")
                if not silent:
                    self.bot.sendMessage(chat_ID, "⚠️ Error retrieving your session. Please try again.")
            return

        if not data:
            return

        username   = data.get("username")
        bedroom_id = data.get("bedroom_id")

        if username and bedroom_id:
            self.set_state(chat_ID, "registered", username=username, bedroom_id=bedroom_id)
            if not silent:
                self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You're in room {bedroom_id}. 👋")
        elif username:
            self.set_state(chat_ID, "waiting_room_name", username=username)
            if not silent:
                self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You don't have a room yet. Let's create one! 🏠")
                self.bot.sendMessage(chat_ID, "What's the room name? Send 'skip' for the default.")



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
