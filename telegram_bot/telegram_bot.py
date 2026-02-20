import json
import os
import time
import threading
import logging
from datetime import datetime

import cherrypy
from dotenv import load_dotenv
import requests
import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardButton, InlineKeyboardMarkup
import bcrypt

logger = logging.getLogger(__name__)


def hash_password(password):
    try:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    except Exception as e:
        logger.error(f"Error hashing password: {e}")
        raise


class TelegramBot:
    exposed = True

    def __init__(self, conf):
        self.catalog_url = conf['catalogURL']
        self.service_info = conf['serviceInfo']
        self.remove_interval = conf.get('removeInterval', 10)
        self._stop_event = threading.Event()
        self._worker = None
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

        self.register_service()

    # --- message routing ---

    def on_chat_message(self, msg):
        content_type, _, chat_ID = telepot.glance(msg)
        if content_type != 'text':
            return

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
            "waiting_room_choice":         self._handle_waiting_room_choice,
            "waiting_room_name":           self._handle_waiting_room_name,
            "waiting_room_password":       self._handle_waiting_room_password,
            "waiting_join_bedroom_id":     self._handle_waiting_join_bedroom_id,
            "waiting_join_password":       self._handle_waiting_join_password,
            "waiting_delete_confirmation": self._handle_delete_room,
            "waiting_leave_confirmation":  self._handle_leave_room,
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
            }
    def on_callback_query(self, msg):
        query_ID, from_ID, query_data = telepot.glance(msg, flavor='callback_query')
        self.bot.answerCallbackQuery(query_ID)

        self._ensure_user_state(from_ID)

        handlers = {
            "create_room": self._cb_create_room,
            "join_room": self._cb_join_room,
            "view_data": self._cb_view_data,
            "manage_settings": self._cb_manage_settings,
            "delete_room": self._cb_delete_room,
            "leave_room": self._cb_leave_room,
            "share_room": self._cb_share_room,
            "view_sensor_data": self._cb_view_sensor_data,
            "main_menu": self._cb_main_menu,
        }

        handler = handlers.get(query_data)

        if handler:
            handler(from_ID)
        else:
            self.bot.sendMessage(from_ID, "Unknown option or feature not implemented yet.")

    def _cb_create_room(self, chat_ID):
        username = self.user_states[chat_ID].get("username")
        self.bot.sendMessage(chat_ID, "You chose to create a room. Please enter the room name:")
        self._set_state(chat_ID, "waiting_room_name", username=username)

    def _cb_join_room(self, chat_ID):
        username = self.user_states[chat_ID].get("username")
        self.bot.sendMessage(chat_ID, "You chose to join a room. Please enter the bedroom ID:")
        self._set_state(chat_ID, "waiting_join_bedroom_id", username=username)

    def _cb_view_data(self, chat_ID):
        self._send_room_data_options(chat_ID)

    def _cb_manage_settings(self, chat_ID):
        self._send_room_settings_options(chat_ID)

    def _cb_delete_room(self, chat_ID):
        self.bot.sendMessage(chat_ID,
                             "Are you sure you want to delete the room? Type 'yes' to confirm.")
        self.user_states[chat_ID]["state"] = "waiting_delete_confirmation"

    def _cb_leave_room(self, chat_ID):
        self.bot.sendMessage(chat_ID,
                             "Are you sure you want to leave the room? Type 'yes' to confirm.")
        self.user_states[chat_ID]["state"] = "waiting_leave_confirmation"

    def _cb_share_room(self, chat_ID):
        room_id = self.user_states[chat_ID].get("bedroom_id")
        self.bot.sendMessage(chat_ID, f"Share this room ID: {room_id}")
        self.bot.sendMessage(chat_ID,
                             "You need to share the room ID and password together.")

    def _cb_view_sensor_data(self, chat_ID):
        self.bot.sendMessage(chat_ID, "Sensor data feature not implemented yet.")
    def _cb_main_menu(self, chat_ID):
        self._send_registered_user_options(chat_ID)
    # --- keyboards options ---

    def _send_room_options(self, chat_ID):
        existing = self.user_states.get(chat_ID, {})
        # no need for separate booleans; rely on presence of username/bedroom_id
        existing["state"] = "waiting_room_choice"
        self.user_states[chat_ID] = existing

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Create a room", callback_data="create_room")],
            [InlineKeyboardButton(text="🚪 Join a room",   callback_data="join_room")],
        ])
        self.bot.sendMessage(chat_ID, "What would you like to do?", reply_markup=keyboard)

    def _send_registered_user_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 View room data",       callback_data="view_data")],
            [InlineKeyboardButton(text="⚙️ Manage room settings", callback_data="manage_settings")],
        ])
        self.bot.sendMessage(chat_ID, "What would you like to do?", reply_markup=keyboard)

    def _send_room_settings_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Change room password", callback_data="change_password")],
            [InlineKeyboardButton(text="🗑️ Delete room",          callback_data="delete_room")],
            [InlineKeyboardButton(text="🚪 Leave room",           callback_data="leave_room")],
            [InlineKeyboardButton(text="👥 Share room",             callback_data="share_room")],
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

        if state == "registered":
            self._send_registered_user_options(chat_ID)
        elif state == "waiting_room_choice":
            self._send_room_options(chat_ID)
        else:
            self.bot.sendMessage(chat_ID, "Welcome to BetterSleep! Use /help to see available commands.")
            self.bot.sendMessage(chat_ID, "To get started, please choose a username:")
            self.user_states[chat_ID] = {"state": "waiting_username", "username": None}

    def _handle_help(self, chat_ID):
        self.bot.sendMessage(chat_ID, "Available commands:\n/start - Start the bot\n/help - Show this help message")

    def _handle_waiting_username(self, chat_ID, message):
        username = message.strip()
        if self._check_username_exists(chat_ID, username):
            self.bot.sendMessage(chat_ID, "Please choose a different username:")
            return

        # mark the username directly; no separate boolean needed
        self._set_state(chat_ID, "waiting_room_choice", username=username)
        self.bot.sendMessage(chat_ID, f"Great! Username '{username}' is available.")
        self._send_room_options(chat_ID)

    def _handle_waiting_room_choice(self, chat_ID, message):
        # user typed instead of pressing a button, just show the menu again
        self._send_room_options(chat_ID)

    def _handle_waiting_room_name(self, chat_ID, message):
        self.user_states[chat_ID]["room_name"] = message
        self.user_states[chat_ID]["state"] = "waiting_room_password"
        self.bot.sendMessage(chat_ID, f"Room '{message}' set. Now enter the password:")

    def _handle_waiting_room_password(self, chat_ID, message):
        room_name = self.user_states[chat_ID].get("room_name")
        username  = self.user_states[chat_ID].get("username")

        if not username:
            self.bot.sendMessage(chat_ID, "Something went wrong, please start over with /start")
            return

        room_id = self._create_bedroom(chat_ID, room_name, hash_password(message))
        if room_id and self._add_user(chat_ID, username, room_id):
            self._finalize_registration(chat_ID, username, room_id)

    def _handle_waiting_join_bedroom_id(self, chat_ID, message):
        self.user_states[chat_ID]["bedroom_id"] = message
        self.user_states[chat_ID]["state"] = "waiting_join_password"
        self.bot.sendMessage(chat_ID, "Enter the password for this room:")

    def _handle_waiting_join_password(self, chat_ID, message):
        room_id  = self.user_states[chat_ID].get("bedroom_id")
        username = self.user_states[chat_ID].get("username")

        if not username:
            self.bot.sendMessage(chat_ID, "Something went wrong, please start over with /start")
            return

        if self._check_room(chat_ID, room_id, message):
            if self._add_user(chat_ID, username, room_id):
                self._finalize_registration(chat_ID, username, room_id, joined=True)
        else:
            self.bot.sendMessage(chat_ID, "Incorrect password or room not found. Please try again.")
            self.user_states[chat_ID]["state"] = "waiting_join_bedroom_id"
            self.bot.sendMessage(chat_ID, "Please enter the bedroom ID:")

    def _handle_delete_room(self, chat_ID, message):
        if message.lower() != "yes":
            self.bot.sendMessage(chat_ID, "Room deletion cancelled.")
            self._send_registered_user_options(chat_ID)
            return

        bedroom_id = self.user_states[chat_ID].get("bedroom_id")
        self._remove_bedroom(bedroom_id)
        self.bot.sendMessage(chat_ID, f"Room {bedroom_id} deleted.")
        self._reset_to_room_choice(chat_ID)

    def _handle_leave_room(self, chat_ID, message):
        if message.lower() != "yes":
            self.bot.sendMessage(chat_ID, "Leave room cancelled.")
            self._send_registered_user_options(chat_ID)
            return

        if self._leave_bedroom(chat_ID):
            self.bot.sendMessage(chat_ID, "You have left the room.")
            self._reset_to_room_choice(chat_ID)
        else:
            self.bot.sendMessage(chat_ID, "Error leaving the room. Please try again later.")

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
        self._send_room_options(chat_ID)

    def _finalize_registration(self, chat_ID, username, room_id, joined=False):
        greeting = "Good morning" if 6 <= datetime.now().hour < 18 else "Good evening"
        if joined:
            self.bot.sendMessage(chat_ID, f"{greeting}, {username}! You have successfully joined room {room_id}.")
        else:
            self.bot.sendMessage(chat_ID, f"{greeting}, {username}! You are now registered in room {room_id}.")

        # store username and bedroom_id; no separate booleans
        self._set_state(chat_ID, "registered",
                        bedroom_id=room_id, username=username)
        self._send_registered_user_options(chat_ID)


    # --- catalog HTTP calls ---

    def _request_catalog(self, method, endpoint, chat_ID, **kwargs):
        try:
            call = getattr(requests, method.lower())
            res = call(f"{self.catalog_url}/{endpoint}", timeout=5, **kwargs)
            res.raise_for_status()
            return res.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout {method} {endpoint} for user {chat_ID}")
            self.bot.sendMessage(chat_ID, "Connection timeout with Catalog.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {method} {endpoint}: {e}")
            if e.response.status_code == 409:
                self.bot.sendMessage(chat_ID, "Conflict: resource already exists.")
        except Exception as e:
            logger.error(f"Unexpected error {method} {endpoint}: {e}")
            self.bot.sendMessage(chat_ID, "Unexpected error occurred.")
        return None

    def _create_bedroom(self, chat_ID, room_name, password):
        data = self._request_catalog("post", "addBedroom", chat_ID,
                                     json={"room_name": room_name, "password": password})
        if data:
            room_id = data.get("bedroom_id")
            self.bot.sendMessage(chat_ID, f"Room '{room_name}' created with ID {room_id}!")
            return room_id
        return None

    def _remove_bedroom(self, bedroom_id):
        try:
            res = requests.delete(f"{self.catalog_url}/removeRoom",
                                  params={"bedroom_id": bedroom_id}, timeout=5)
            res.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error removing bedroom {bedroom_id}: {e}")
            return False

    def _leave_bedroom(self, chat_ID):
        try:
            res = requests.put(f"{self.catalog_url}/leaveBedroom",
                               json={"telegram_chat_id": chat_ID}, timeout=5)
            res.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Error leaving room for user {chat_ID}: {e}")
            return False

    def _check_room(self, chat_ID, room_id, password):
        data = self._request_catalog("get", "checkRoom", chat_ID,
                                     params={"bedroom_id": room_id, "password": password})
        return data is not None

    def _check_username_exists(self, chat_ID, username):
        data = self._request_catalog("get", "checkUsername", chat_ID,
                                     params={"username": username})
        if data and data.get("exists"):
            self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another.")
            return True
        return False

    def _add_user(self, chat_ID, username, bedroom_id):
        session = self._get_user_session(chat_ID)
        if session and session.get("username"):
            data = self._request_catalog("put", "associateUserToBedroom", chat_ID,
                                         json={"telegram_chat_id": chat_ID, "bedroom_id": bedroom_id})
        else:
            data = self._request_catalog("post", "addUser", chat_ID,
                                         json={"username": username, "telegram_chat_id": chat_ID, "bedroom_id": bedroom_id})
        return data is not None

    def _get_user_session(self, chat_ID):
        return self._request_catalog("get", "getUserSession", chat_ID,
                                     params={"telegram_chat_id": chat_ID})

    def _handle_restore_user_session(self, chat_ID):
        try:
            res = requests.get(f"{self.catalog_url}/getUserSession",
                               params={"telegram_chat_id": chat_ID}, timeout=5)
            res.raise_for_status()
            data = res.json()
            username   = data.get("username")
            bedroom_id = data.get("bedroom_id")

            if username and bedroom_id:
                # set username and bedroom_id; no extra booleans
                self._set_state(chat_ID, "registered",
                                bedroom_id=bedroom_id, username=username)
                self.bot.sendMessage(chat_ID, f"Welcome back, {username} from room {bedroom_id}!")
            elif username:
                self._set_state(chat_ID, "waiting_room_choice",
                                username=username)
                self.bot.sendMessage(chat_ID, f"Welcome back, {username}! You don't have a room yet.")

        except requests.exceptions.Timeout:
            self.bot.sendMessage(chat_ID, "Connection timeout with Catalog. Please try again.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                self.bot.sendMessage(chat_ID, "Error connecting to Catalog. Please try again.")
        except requests.exceptions.ConnectionError:
            self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
        except Exception as e:
            logger.error(f"Unexpected error restoring session: {e}")
            self.bot.sendMessage(chat_ID, "Unexpected error. Please try again.")

    # --- service registration ---

    def register_service(self):
        service = {
            "serviceID":   self.service_info['serviceID'],
            "name":        self.service_info['name'],
            "endpoint":    f"http://{self.service_info['host']}:{self.service_info['port']}",
            "type":        self.service_info.get('type', 'TelegramBot'),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            res = requests.post(f'{self.catalog_url}/addService', json=service, timeout=5)
            res.raise_for_status()
            logger.info('Registered with Catalog')
        except Exception as e:
            logger.error(f'Registration failed: {e}')
            self.stop_background_loop()

    def update_service(self):
        service = {
            "serviceID":   self.service_info['serviceID'],
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            res = requests.put(f'{self.catalog_url}/updateServiceLastUpdate', json=service, timeout=5)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f'Update failed: {e}')

    def unregister_service(self):
        try:
            res = requests.delete(f'{self.catalog_url}/removeService',
                                  params={'serviceID': self.service_info['serviceID']}, timeout=5)
            res.raise_for_status()
            logger.info('Unregistered from Catalog')
        except Exception as e:
            logger.error(f'Unregister failed: {e}')

    def start_background_loop(self):
        if self._worker is not None:
            return

        def _loop():
            while not self._stop_event.is_set():
                time.sleep(self.remove_interval)
                self.update_service()

        self._worker = threading.Thread(target=_loop, daemon=True)
        self._worker.start()

    def stop_background_loop(self):
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=2)
            self._worker = None



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

    cherrypy.engine.subscribe('start', bot.start_background_loop)
    cherrypy.engine.subscribe('stop',  bot.stop_background_loop)
    cherrypy.engine.subscribe('stop',  bot.unregister_service)

    cherrypy.engine.start()
    cherrypy.engine.block()