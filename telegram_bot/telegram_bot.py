import json
import os
import time
import threading
import logging
from datetime import datetime

import cherrypy
from dotenv import load_dotenv
import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardButton, InlineKeyboardMarkup

from catalog_client import CatalogClient

logger = logging.getLogger(__name__)


class TelegramBot:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        # catalog client
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self.catalog = CatalogClient(self.catalog_url,self.service_info, remove_interval=self.remove_interval)
        self.chatIDs = []
        self.user_states = {}

        load_dotenv()
        self.token = os.getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN not found in .env")

        self.bot = telepot.Bot(self.token)
        MessageLoop(self.bot, {
            'chat': self.on_chat_message,
            'callback_query': self.on_callback_query
        }).run_as_thread()

        # start catalog heartbeat (register + periodic update)
        try:
            self.catalog.register_service()

        except Exception as e:
            logger.error(f'Failed to start catalog heartbeat: {e}')

    # --- message routing ---

    def on_chat_message(self, msg):
        content_type, _, chat_ID = telepot.glance(msg)
        if content_type != 'text':
            return

        # ensure state exists for this chat
        self._ensure_user_state(chat_ID)

        text = msg['text']

        if text == "/start":
            self._handle_start(chat_ID)
            return
        if text == "/help":
            self._handle_help(chat_ID)
            return

        state = self.user_states.get(chat_ID, {}).get("state")
        #get the current state of the user and dispatch to the appropriate handler
        if state:
            self._dispatch_state(chat_ID, state, text)

    def _dispatch_state(self, chat_ID, state, message):
        handlers = {
            "waiting_username":            self._handle_waiting_username,
            "waiting_room_name":           self._handle_waiting_room_name,
            "waiting_room_bedtime":        self._handle_waiting_room_bedtime,
            "waiting_room_wakeup":         self._handle_waiting_room_wakeup,
            "waiting_room_temp":           self._handle_waiting_room_temp,
            "waiting_delete_confirmation": self._handle_delete_room,
            "waiting_add_device_name":     self._handle_waiting_add_device_name,
            "waiting_remove_device_choice": self._handle_waiting_remove_device_choice,
        }
        handler = handlers.get(state)
        if handler:
            handler(chat_ID, message)
    # --- callback query routing ---
    def _ensure_user_state(self, chat_ID):
        if chat_ID not in self.user_states:
            # store only the meaningful state fields; remove redundant booleans
            self.user_states[chat_ID] = {
                "state": None,
                "username": None,
                "bedroom_id": None,
                # device flow helpers
                "devices_list": None,
                "pending_device_type": None,
                # temporary room creation fields
                "new_room_name": None,
                "new_room_bedtime": None,
                "new_room_wakeup": None,
                "new_room_desired_temp": None,
            }
    def on_callback_query(self, msg):
        query_ID, from_ID, query_data = telepot.glance(msg, flavor='callback_query')
        self.bot.answerCallbackQuery(query_ID)

        self._ensure_user_state(from_ID)

        handlers = {
            "create_room": self._cb_create_room,
            "view_data": self._cb_view_data,
            "manage_settings": self._cb_manage_settings,
            "manage_devices": self._cb_manage_devices,
            "delete_room": self._cb_delete_room,
            "view_sensor_data": self._cb_view_sensor_data,
            "view_sleep_quality": self._cb_view_sleep_quality,
            "main_menu": self._cb_main_menu,
            "remove_device": self.cb_remove_device,
            "add_device" : self._send_type_of_device_options,
            "add_device_light": lambda cid: self.cb_add_device(cid, type="light"),
            "add_device_heater": lambda cid: self.cb_add_device(cid, type="heater"),
            "add_device_fan": lambda cid: self.cb_add_device(cid, type="fan"),
        }

        handler = handlers.get(query_data)

        if handler:
            handler(from_ID)
        else:
            self.bot.sendMessage(from_ID, "Unknown option or feature not implemented yet.")

    def _cb_create_room(self, chat_ID):
        # begin manual room creation: ask for room name first
        username = self.user_states[chat_ID].get("username")
        if not username:
            self.bot.sendMessage(chat_ID, "You need a username before creating a room. Please use /start to register.")
            return
        self.bot.sendMessage(chat_ID, "📝 Creating a new room — what's the room name? (e.g. 'Bedroom')")
        self._set_state(chat_ID, "waiting_room_name", username=username)

    def _cb_view_data(self, chat_ID):
        self._send_room_data_options(chat_ID)

    def _cb_manage_settings(self, chat_ID):
        # Open settings menu (room settings + device management)
        self._send_room_settings_options(chat_ID)

    def _cb_manage_devices(self, chat_ID):
        # Entry point for device management
        self._send_device_management_options(chat_ID)

    def _cb_delete_room(self, chat_ID):
        self.bot.sendMessage(chat_ID,
                             "Are you sure you want to delete the room? Type 'yes' to confirm.")
        self.user_states[chat_ID]["state"] = "waiting_delete_confirmation"

    def _cb_view_sensor_data(self, chat_ID):
        self.bot.sendMessage(chat_ID, "🔎 Sensor data feature not implemented yet.")

    def _cb_view_sleep_quality(self, chat_ID):
        self.bot.sendMessage(chat_ID, "💤 Sleep quality feature not implemented yet.")

    def _cb_main_menu(self, chat_ID):
        self._send_registered_user_options(chat_ID)

    def cb_add_device(self, chat_ID,type=None):
        # store the chosen device type in the user's temporary state and ask only for the name
        if type not in ("light", "heater", "fan"):
            self.bot.sendMessage(chat_ID, "Unsupported device type. Please choose one of the available types.")
            return
        self.user_states[chat_ID]["pending_device_type"] = type
        self.bot.sendMessage(chat_ID, f"➕ Great! What's the name for the {type} device? 🏷️")
        self._set_state(chat_ID, "waiting_add_device_name")




    def cb_remove_device(self, chat_ID):
        # start the numbered remove flow
        self._begin_remove_device(chat_ID)



    def _send_device_management_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add device", callback_data="add_device")],
            [InlineKeyboardButton(text="🗑️ Remove device", callback_data="remove_device")],
            [InlineKeyboardButton(text="⬅️ Back to main menu", callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "Device management options:", reply_markup=keyboard)

    def _send_type_of_device_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💡 Light", callback_data="add_device_light")],
            [InlineKeyboardButton(text="🌡️ Heater", callback_data="add_device_heater")],
            [InlineKeyboardButton(text="❄️ Fan", callback_data="add_device_fan")],
            [InlineKeyboardButton(text="⬅️ Back to device management", callback_data="manage_devices")],
        ])
        self.bot.sendMessage(chat_ID, "Select the type of device to add:", reply_markup=keyboard)
    def _send_registered_user_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 View room data",       callback_data="view_data")],
            [InlineKeyboardButton(text="🔧 Manage devices", callback_data="manage_devices")],
            [InlineKeyboardButton(text="⚙️ Manage room settings", callback_data="manage_settings")],
        ])
        self.bot.sendMessage(chat_ID, "What would you like to do?", reply_markup=keyboard)

    def _send_room_settings_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑️ Delete room",          callback_data="delete_room")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",    callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "What would you like to do?", reply_markup=keyboard)

    def _send_room_data_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📈View sensor data", callback_data="view_sensor_data")],
            [InlineKeyboardButton(text="📉View sleep quality", callback_data="view_sleep_quality")],
            [InlineKeyboardButton(text="⬅️ Back to main menu",   callback_data="main_menu")],
        ])
        self.bot.sendMessage(chat_ID, "What data would you like to view?", reply_markup=keyboard)
    # --- state handlers ---

    def _handle_start(self, chat_ID):
        if chat_ID not in self.chatIDs:
            self.chatIDs.append(chat_ID)

        self._handle_restore_user_session(chat_ID)
        state = self.user_states.get(chat_ID, {}).get("state")

        # If the restore set a state (e.g. waiting_room_name) we should not overwrite it.
        if state == "registered":
            self._send_registered_user_options(chat_ID)
            return

        if state:
            # there's already a pending state (e.g. waiting_room_name) set during restore; do nothing
            return

        # fresh user: prompt to choose username
        self.bot.sendMessage(chat_ID, "Welcome to BetterSleep! Use /help to see available commands.")
        self.bot.sendMessage(chat_ID, "To get started, please choose a username:")
        self._set_state(chat_ID, "waiting_username", username=None)

    def _handle_help(self, chat_ID):
        self.bot.sendMessage(chat_ID, "🤖 Available commands:\n/start - Start the bot\n/help - Show this help message")

    def _handle_waiting_username(self, chat_ID, message):
        username = message.strip()
        if self._check_username_exists(chat_ID, username):
            self.bot.sendMessage(chat_ID, "Please choose a different username:")
            return

        # Start interactive room creation: ask for the room name first, then bedtime/wakeup/temperature.
        # Store username and move to the `waiting_room_name` state so the bot will ask for bedtime/wakeup/temp afterwards.
        self._set_state(chat_ID, "waiting_room_name", username=username)
        self.bot.sendMessage(chat_ID, f"🎉 Great choice, {username}! Let's set up your personal room. What's the room name? Send 'skip' to use the default name.")

    def _handle_waiting_room_name(self, chat_ID, message):
        room_name = message.strip()
        username = self.user_states[chat_ID].get("username")
        if not username:
            self.bot.sendMessage(chat_ID, "Something went wrong, please start over with /start")
            return

        # allow the user to type 'skip' to use a default room name
        if room_name.lower() == 'skip' or room_name == '':
            room_name = f"{username}'s room"

        # store the room name and ask for bedtime
        self.user_states[chat_ID]["new_room_name"] = room_name
        self.bot.sendMessage(chat_ID, "🕰️ What is the bedtime for this room? Please reply in HH:MM (24h) format, e.g. 23:00")
        self._set_state(chat_ID, "waiting_room_bedtime")

    def _handle_waiting_room_bedtime(self, chat_ID, message):
        text = message.strip()
        # accept HH:MM or HH:MM:SS
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                bedtime = dt.strftime("%H:%M:%S")
                break
            except Exception:
                bedtime = None
        if not bedtime:
            self.bot.sendMessage(chat_ID, "Invalid time format. Please send bedtime in HH:MM (24h) format, e.g. 23:00")
            return
        self.user_states[chat_ID]["new_room_bedtime"] = bedtime
        self.bot.sendMessage(chat_ID, "⏰ Now send the wakeup time in HH:MM (24h), e.g. 07:00")
        self._set_state(chat_ID, "waiting_room_wakeup")

    def _handle_waiting_room_wakeup(self, chat_ID, message):
        text = message.strip()
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                dt = datetime.strptime(text, fmt)
                wakeup = dt.strftime("%H:%M:%S")
                break
            except Exception:
                wakeup = None
        if not wakeup:
            self.bot.sendMessage(chat_ID, "Invalid time format. Please send wakeup in HH:MM (24h) format, e.g. 07:00")
            return
        self.user_states[chat_ID]["new_room_wakeup"] = wakeup
        self.bot.sendMessage(chat_ID, "🌡️ Finally, what's the desired temperature? Send a number (e.g. 21.5)")
        self._set_state(chat_ID, "waiting_room_temp")

    def _handle_waiting_room_temp(self, chat_ID, message):
        text = message.strip()
        try:
            temp = float(text)
        except Exception:
            self.bot.sendMessage(chat_ID, "Invalid temperature. Please send a number, e.g. 22 or 21.5")
            return
        # basic sanity range
        if temp < 5 or temp > 35:
            self.bot.sendMessage(chat_ID, "Please choose a temperature between 5 and 35 °C.")
            return
        self.user_states[chat_ID]["new_room_desired_temp"] = temp

        # all collected — create the room
        room_name = self.user_states[chat_ID].get("new_room_name")
        bedtime = self.user_states[chat_ID].get("new_room_bedtime")
        wakeup = self.user_states[chat_ID].get("new_room_wakeup")
        desired_temp = self.user_states[chat_ID].get("new_room_desired_temp")

        self.bot.sendMessage(chat_ID, f"🔨 Creating room '{room_name}' with bedtime {bedtime}, wakeup {wakeup} and desired temp {desired_temp}°C...")
        room_id = self._create_bedroom(chat_ID, room_name, bedtime=bedtime, wakeup=wakeup, desired_temperature=desired_temp)
        username = self.user_states[chat_ID].get("username")
        if room_id and self._add_user(chat_ID, username, room_id):
            self._finalize_registration(chat_ID, username, room_id)
        else:
            self.bot.sendMessage(chat_ID, "Couldn't create the room right now. Please try again later.")
            self._set_state(chat_ID, "waiting_room_choice", username=username)

    def _handle_delete_room(self, chat_ID, message):
        if message.lower() != "yes":
            self.bot.sendMessage(chat_ID, "Room deletion cancelled.")
            self._send_registered_user_options(chat_ID)
            return

        bedroom_id = self.user_states[chat_ID].get("bedroom_id")
        self._remove_bedroom(bedroom_id)
        self.bot.sendMessage(chat_ID, f"Room {bedroom_id} deleted.")
        self._reset_to_room_choice(chat_ID)


    def _begin_remove_device(self, chat_ID):
        # fetch devices for this user's bedroom and present numbered list
        bedroom_id = self.user_states.get(chat_ID, {}).get("bedroom_id")
        if not bedroom_id:
            self.bot.sendMessage(chat_ID, "You are not associated with a room.")
            return
        res = self.catalog.get("getDevices", params={"bedroom_id": bedroom_id})
        if not res or res.get("status") != "success":
            self.bot.sendMessage(chat_ID, "Could not retrieve devices or no devices found.")
            return
        devices = res.get("devices", [])
        if not devices:
            self.bot.sendMessage(chat_ID, "No devices found in your room.")
            return
        # store list and show numbered options
        self.user_states[chat_ID]["devices_list"] = devices
        msg_lines = ["Select the device to remove (send the number):"]
        for i, d in enumerate(devices):
            msg_lines.append(f"{i}: {d.get('device_id')} ({d.get('device_name')})")
        self.bot.sendMessage(chat_ID, "\n".join(msg_lines))
        self._set_state(chat_ID, "waiting_remove_device_choice")

    def _handle_waiting_remove_device_choice(self, chat_ID, message):
        choice = message.strip()
        if not choice.isdigit():
            self.bot.sendMessage(chat_ID, "Please send a valid number corresponding to the device you want to remove.")
            return
        idx = int(choice)
        devices = self.user_states.get(chat_ID, {}).get("devices_list", [])
        if idx < 0 or idx >= len(devices):
            self.bot.sendMessage(chat_ID, "Number out of range. Please try again.")
            return
        device = devices[idx]
        device_id = device.get('device_id')
        # call catalog delete
        res = self.catalog.delete("removeDevice", params={"deviceID": device_id})
        if res is not None:
            # assume success response is JSON with status or simply accepted
            self.bot.sendMessage(chat_ID, f"✅ Device {device_id} removed.")
        else:
            self.bot.sendMessage(chat_ID, f"❌ Failed to remove device {device_id}.")
        # cleanup state
        self.user_states[chat_ID].pop("devices_list", None)
        self._reset_to_room_choice(chat_ID)

    def _handle_waiting_add_device_name(self, chat_ID, message):
        name = message.strip()
        if not name:
            self.bot.sendMessage(chat_ID, "Please send a non-empty name for the device.")
            return
        if len(name) > 64:
            self.bot.sendMessage(chat_ID, "Please choose a shorter name (max 64 characters).")
            return

        pending_type = self.user_states.get(chat_ID, {}).get("pending_device_type")
        if not pending_type:
            self.bot.sendMessage(chat_ID, "Device type not selected. Please start again from Manage devices.")
            self._reset_to_room_choice(chat_ID)
            return

        bedroom_id = self.user_states.get(chat_ID, {}).get("bedroom_id")
        if not bedroom_id:
            self.bot.sendMessage(chat_ID, "You don't have a room associated. Please run /start to register or create a room first.")
            self._reset_to_room_choice(chat_ID)
            return

        payload = {
            "device_name": name,
            "device_type": pending_type,
            "bedroom_id": bedroom_id,
            "value": 0
        }

        self.bot.sendMessage(chat_ID, f"🔧 Creating {pending_type} device named '{name}'...")
        res = self.catalog.post("addDevice", json=payload)
        if res and res.get("status") == "success":
            device_id = res.get("device_id") or res.get("id") or "(unknown)"
            self.bot.sendMessage(chat_ID, f"✅ Device created: {name} (id: {device_id})")
        else:
            # try to show error message if available
            err = res.get("error") if isinstance(res, dict) else None
            if err:
                self.bot.sendMessage(chat_ID, f"❌ Could not create device: {err}")
            else:
                self.bot.sendMessage(chat_ID, "❌ Could not create device. Please try again later.")

        # cleanup pending fields and return to registered menu
        self.user_states[chat_ID]["pending_device_type"] = None
        self._set_state(chat_ID, "registered",
                        bedroom_id=bedroom_id, username=self.user_states[chat_ID].get("username"))
        self._send_registered_user_options(chat_ID)

    # --- small helpers ---

    def _set_state(self, chat_ID, state, **kwargs):
        entry = self.user_states.get(chat_ID, {})
        entry["state"] = state
        entry.update(kwargs)
        self.user_states[chat_ID] = entry

    def _reset_to_room_choice(self, chat_ID):
        username = self.user_states[chat_ID].get("username")
        # rely on username presence instead of a separate boolean
        self._set_state(chat_ID, "waiting_room_choice",
                        username=username)

    def _finalize_registration(self, chat_ID, username, room_id, joined=False):
        greeting = "Good morning" if 6 <= datetime.now().hour < 18 else "Good evening"
        if joined:
            self.bot.sendMessage(chat_ID, f"{greeting} ☀️, {username}! You have successfully joined room {room_id}.")
        else:
            self.bot.sendMessage(chat_ID, f"{greeting} 🌙, {username}! Your personal room {room_id} is ready. Happy sleeping! 🛌")

        # store username and bedroom_id; no separate booleans
        self._set_state(chat_ID, "registered",
                        bedroom_id=room_id, username=username)
        self._send_registered_user_options(chat_ID)


    # --- catalog HTTP calls ---

    def _create_bedroom(self, chat_ID, room_name, bedtime=None, wakeup=None, desired_temperature=None):
        # create room; include bedtime/wakeup/desired_temperature if provided
        payload = {
            "room_name": room_name,
            # catalog/db expects these fields not null; if not provided use sensible defaults
            "bedtime": bedtime or "23:00:00",
            "wakeup": wakeup or "07:00:00",
            "desired_temperature": desired_temperature if desired_temperature is not None else 22.0,
        }
        data = self.catalog.post("addBedroom", json=payload)
        if data:
            room_id = data.get("bedroom_id")
            self.bot.sendMessage(chat_ID, f"✅ Room '{room_name}' created — ID: {room_id}")
            return room_id
        return None

    def _remove_bedroom(self, bedroom_id):
        res = self.catalog.delete("removeRoom", params={"bedroom_id": bedroom_id})
        if res is not None:
            return True
        logger.error(f"Error removing bedroom {bedroom_id}: catalog returned error")
        return False

    def _check_username_exists(self, chat_ID, username):
        data = self.catalog.get("checkUsername", params={"username": username})
        if data and data.get("exists"):
            self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another.")
            return True
        return False

    def _add_user(self, chat_ID, username, bedroom_id):
        # Simplify: always call addUser to register the user with the bedroom_id (if provided)
        data = self.catalog.post("addUser", json={"username": username, "telegram_chat_id": chat_ID, "bedroom_id": bedroom_id})
        return data is not None

    def _get_user_session(self, chat_ID):
        return self.catalog.get("getUserSession", params={"telegram_chat_id": chat_ID})

    def _handle_restore_user_session(self, chat_ID):
        try:
            data = self.catalog.get("getUserSession", params={"telegram_chat_id": chat_ID})
            if not data:
                # catalog returned error or no session
                return

            username = data.get("username")
            bedroom_id = data.get("bedroom_id")

            if username and bedroom_id:
                # set username and bedroom_id; no extra booleans
                self._set_state(chat_ID, "registered",
                                bedroom_id=bedroom_id, username=username)
                self.bot.sendMessage(chat_ID, f"Welcome back, {username} from room {bedroom_id}!")
            elif username:
                # username exists but no room: start interactive room creation
                self._set_state(chat_ID, "waiting_room_name", username=username)
                self.bot.sendMessage(chat_ID, f"Welcome back, {username}! Let's create your room. What's the room name? Send 'skip' to use a default name.")

        except Exception as e:
            logger.error(f"Unexpected error restoring session: {e}")
            self.bot.sendMessage(chat_ID, "Unexpected error. Please try again.")




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

