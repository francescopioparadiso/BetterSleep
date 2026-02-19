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

# Configure logging
logger = logging.getLogger(__name__)


def hash_password(password):
    """Hash a password using bcrypt."""
    try:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        return hashed
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

        load_dotenv()
        self.token = os.getenv("TELEGRAM_TOKEN")
        if not self.token:
            logger.error("TELEGRAM_TOKEN not found in environment variables")
            raise ValueError("TELEGRAM_TOKEN environment variable is required")

        try:
            self.bot = telepot.Bot(self.token)
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            raise
        self.chatIDs = []
        self.user_states = {}
        MessageLoop(self.bot, {'chat': self.on_chat_message, 'callback_query': self.on_callback_query}).run_as_thread()
        self.register_service()

    def on_chat_message(self, msg):
        content_type, chat_type, chat_ID = telepot.glance(msg)
        if content_type != 'text':
            return

        message = msg['text']

        if message == "/start":
            self._handle_start(chat_ID)
            return

        if message == "/help":
            self._handle_help(chat_ID)
            return

        state_info = self.user_states.get(chat_ID)
        if not state_info:
            return

        curr_state = state_info.get("state")
        self._dispatch_state(chat_ID, curr_state, message)

########################################################################
#   Methods to send different options to the user based on their state
########################################################################
    def _send_room_options(self, chat_ID):
        """Send keyboard options to create or join a room."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Create a room", callback_data="create_room")],
            [InlineKeyboardButton(text="🚪 Join a room", callback_data="join_room")]
        ])
        self.bot.sendMessage(chat_ID, text="What would you like to do?", reply_markup=keyboard)

    def _send_registered_user_options(self, chat_ID):
        """Send keyboard options for registered users."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 View room data", callback_data="view_data")],
            [InlineKeyboardButton(text="⚙️ Manage room settings", callback_data="manage_settings")]
        ])
        self.bot.sendMessage(chat_ID, text="What would you like to do?", reply_markup=keyboard)

    def _send_room_settings_options(self, chat_ID):
        """Send keyboard options for room settings management."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Change room password", callback_data="change_password")],
             [InlineKeyboardButton(text="🗑️ Delete room", callback_data="delete_room")],
             [InlineKeyboardButton(text="⬅️ Back to main menu", callback_data="main_menu")]
        ])
        self.bot.sendMessage(chat_ID, text="What would you like to do?", reply_markup=keyboard)

    def on_callback_query(self, msg):
        """Handle callback queries from inline keyboards."""
        query_ID, from_ID, query_data = telepot.glance(msg, flavor='callback_query')
        self.bot.answerCallbackQuery(query_ID)

        if query_data == "create_room":
            self.bot.sendMessage(from_ID, text="You chose to create a room. Please enter the name of the room:")
            self.user_states[from_ID] = {"state": "waiting_room_name", "username": self.user_states[from_ID].get("username")}
        elif query_data == "join_room":
            self.bot.sendMessage(from_ID, text="You chose to join a room. Please enter the ID of the bedroom:")
            self.user_states[from_ID] = {"state": "waiting_join_bedroom_id", "username": self.user_states[from_ID].get("username")}
        elif query_data == "view_data":
            self.bot.sendMessage(from_ID, text="This feature is not implemented yet.")
        elif query_data == "manage_settings":
            self._send_room_settings_options(from_ID)
        elif query_data == "delete_room":
            self.bot.sendMessage(from_ID, text="Are you sure you want to delete the room? This action cannot be undone. Type 'yes' to confirm.")
            self.user_states[from_ID]["state"] = "waiting_delete_confirmation"






    def _dispatch_state(self, chat_ID, curr_state, message):
        """Dispatch user message to appropriate handler based on current state."""
        handlers = {
            "waiting_username": self._handle_waiting_username,
            "waiting_room_name": self._handle_waiting_room_name,
            "waiting_room_password": self._handle_waiting_room_password,
            "waiting_join_bedroom_id": self._handle_waiting_join_bedroom_id,
            "waiting_join_password": self._handle_waiting_join_password,
            "waiting_delete_confirmation": self._handle_delete_room,
            "registered": self._handle_registered_user
        }
        handler = handlers.get(curr_state)
        if handler:
            handler(chat_ID, message)

########################################################################
#   Handlers for different user states and commands
########################################################################
    def _handle_start(self, chat_ID):
        """
        Handle the /start command. If the user is new, ask for username first.
        If user exists, restore session and show options.
        """
        if chat_ID not in self.chatIDs:
            self.chatIDs.append(chat_ID)

        self.bot.sendMessage(chat_ID, text="Welcome to BetterSleep! Use /help to see available commands.")
        self._handle_restore_user_session(chat_ID)

        current_state = self.user_states.get(chat_ID, {}).get("state")

        if current_state == "registered":
            self._send_registered_user_options(chat_ID)
        else:
            # New user - ask for username first
            self.bot.sendMessage(chat_ID, text="Please enter your username to get started:")
            self.user_states[chat_ID] = {"state": "waiting_username"}
    def _handle_help(self, chat_ID):
        """Display available commands to the user."""
        self.bot.sendMessage(chat_ID,
                             text="Available commands:\n/start - Start the bot\n/help - Show this help message")

    def _handle_waiting_username(self, chat_ID, message):
        """
        Handle the state where the user is expected to provide a username.
        This is the first step in the registration flow.
        Check if username exists, and if not, store it and ask user to choose a room.
        """
        username = message.strip()

        if self._check_username_exists(chat_ID, username):
            self.bot.sendMessage(chat_ID, "Please choose a different username:")
            return

        # Store username in state
        self.user_states[chat_ID]["username"] = username
        self.bot.sendMessage(chat_ID, f"Great! Username '{username}' is available.")

        # Now ask user to choose between creating or joining a room
        self._send_room_options(chat_ID)

    def _handle_registered_user(self, chat_ID, message):
        """
        Handle messages from registered users. This can be extended to provide more functionality based on user input.
        """
        username = self.user_states[chat_ID].get("username", "User")
        bedroom_id = self.user_states[chat_ID].get("bedroom_id", "N/A")
        # se e giorno invia Good morning, altrimenti Good evening
        #!TODO Implement this


    def _handle_waiting_room_name(self, chat_ID, message):
        """
        Handle the state where the user is expected to provide a room name for creating a new bedroom.
        Store the room name and transition to the next state to ask for the password.
        """
        self.user_states[chat_ID]["room_name"] = message
        self.user_states[chat_ID]["state"] = "waiting_room_password"
        self.bot.sendMessage(chat_ID, f"Room '{message}' set. Now enter the password:")

    def _handle_restore_user_session(self, chat_ID):
        """
        Attempt to restore a user's session by checking if their Telegram chat ID is associated with an existing user in the Catalog.
        If a session is found, update the user's state to "registered" and welcome them back
        """
        try:
            res = requests.get(f"{self.catalog_url}/getUserSession", params={"telegram_chat_id": chat_ID}, timeout=5)
            res.raise_for_status()

            data = res.json()
            username = data.get("username")
            bedroom_id = data.get("bedroom_id")
            self.user_states[chat_ID] = {
                "state": "registered",
                "bedroom_id": bedroom_id,
                "username": username
            }
            self.bot.sendMessage(chat_ID, f"Welcome back, {username} from room {bedroom_id}!")
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout while restoring user session for chat_ID {chat_ID}")
            self.bot.sendMessage(chat_ID, "Connection timeout with Catalog. Please try again.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.debug(f"No existing session found for chat_ID {chat_ID}")
            else:
                logger.error(f"HTTP error while restoring session: {e}")
                self.bot.sendMessage(chat_ID, "Error connecting to Catalog. Please try again.")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error with Catalog: {e}")
            self.bot.sendMessage(chat_ID, "Connection error with Catalog. Unable to restore session.")
        except Exception as e:
            logger.error(f"Unexpected error restoring user session: {e}")
            self.bot.sendMessage(chat_ID, "Unexpected error. Please try again.")

    def _handle_waiting_room_password(self, chat_ID, message):
        """
        Handle the state where the user is expected to provide a password for the new bedroom.
        Create the room and then register the user with the stored username.
        """
        room_name = self.user_states[chat_ID].get("room_name")
        username = self.user_states[chat_ID].get("username")

        if not username:
            logger.error(f"Username not found in state for chat_ID {chat_ID}")
            self.bot.sendMessage(chat_ID, "Error: username not found. Please start over with /start")
            return

        password_hash = hash_password(message)
        room_id = self._create_bedroom(chat_ID, room_name, password_hash)

        if room_id:
            # Register user with the stored username and new room
            if self._add_user(chat_ID, username, room_id):
                if 6 <= datetime.now().hour < 18:
                    greeting = "Good morning"
                else:
                    greeting = "Good evening"

                self.bot.sendMessage(chat_ID,
                                     f"{greeting}, {username} from room {room_id}! You are now registered.")
                self.user_states[chat_ID] = {
                    "state": "registered",
                    "bedroom_id": room_id,
                    "username": username
                }
                self._send_registered_user_options(chat_ID)

    def _handle_waiting_join_bedroom_id(self, chat_ID, message):
        """
        Handle the state where the user is expected to provide the ID of the bedroom they want to join.
        Store the bedroom ID and transition to the next state to ask for the password.
        """
        self.user_states[chat_ID]["bedroom_id"] = message
        self.user_states[chat_ID]["state"] = "waiting_join_password"
        self.bot.sendMessage(chat_ID, "Enter the password for this room:")

    def _handle_waiting_join_password(self, chat_ID, message):
        """
        Handle the state where the user is expected to provide the password for the bedroom they want to join.
        If password is correct, register the user with the stored username.
        """
        room_id = self.user_states[chat_ID].get("bedroom_id")
        username = self.user_states[chat_ID].get("username")

        if not username:
            logger.error(f"Username not found in state for chat_ID {chat_ID}")
            self.bot.sendMessage(chat_ID, "Error: username not found. Please start over with /start")
            return

        if self._check_room(chat_ID, room_id, message):
            # Register user with the stored username and joined room
            if self._add_user(chat_ID, username, room_id):
                if 6 <= datetime.now().hour < 18:
                    greeting = "Good morning"
                else:
                    greeting = "Good evening"

                self.bot.sendMessage(chat_ID,
                                     f"{greeting}, {username}! You have successfully joined room {room_id}.")
                self.user_states[chat_ID] = {
                    "state": "registered",
                    "bedroom_id": room_id,
                    "username": username
                }
                self._send_registered_user_options(chat_ID)
        else:
            self.bot.sendMessage(chat_ID, "Incorrect password or room not found. Please try again.")
            self.user_states[chat_ID]["state"] = "waiting_join_bedroom_id"
            self.bot.sendMessage(chat_ID, "Please enter the ID of the bedroom:")

    def _handle_delete_room(self, chat_ID, message):
        """
        Handle the state where the user is expected to confirm the deletion of the room.
        If the user confirms, delete the room from the Catalog and reset the user's state.
        """
        if message.lower() == "yes":
            bedroom_id = self.user_states[chat_ID].get("bedroom_id")
            self._remove_bedroom(bedroom_id)
            self.bot.sendMessage(chat_ID, f"Room {bedroom_id} deleted. You can create a new room or join an existing one.")
            # Reset to waiting for room choice
            username = self.user_states[chat_ID].get("username")
            self.user_states[chat_ID] = {"state": "waiting_username", "username": username}
            self._send_room_options(chat_ID)
        else:
            self.bot.sendMessage(chat_ID, "Room deletion cancelled.")
            self._send_registered_user_options(chat_ID)

########################################################################
#   Helper methods to interact with the Catalog
########################################################################
    def _request_catalog(self, method, endpoint, chat_ID, **kwargs):
        """Generic helper to call Catalog API with error handling."""
        try:
            if method.lower() == "get":
                res = requests.get(f"{self.catalog_url}/{endpoint}", timeout=5, **kwargs)
            elif method.lower() == "post":
                res = requests.post(f"{self.catalog_url}/{endpoint}", timeout=5, **kwargs)
            else:
                raise ValueError("Unsupported HTTP method")
            res.raise_for_status()
            return res.json()
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout {method} {endpoint} for user {chat_ID}")
            self.bot.sendMessage(chat_ID, "Connection timeout with Catalog.")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {method} {endpoint}: {e}")
            if e.response.status_code == 409:
                self.bot.sendMessage(chat_ID, "Conflict: resource already exists or registered")
            else:
                self.bot.sendMessage(chat_ID, "Access denied or request failed.")
        except Exception as e:
            logger.error(f"Unexpected error {method} {endpoint}: {e}")
            self.bot.sendMessage(chat_ID, "Unexpected error occurred.")
        return None

    def _create_bedroom(self, chat_ID, room_name, password):
        """Create a new bedroom in the Catalog."""
        bedroom = {"room_name": room_name, "password": password}
        data = self._request_catalog("post", "addBedroom", chat_ID, json=bedroom)
        if data:
            room_id = data.get("bedroom_id")
            self.bot.sendMessage(chat_ID, f"Successfully created room '{room_name}' with ID {room_id}!")
            return room_id
        return None

    def _remove_bedroom(self, bedroom_id):
        """Remove a bedroom from the Catalog."""
        try:
            res = requests.delete(
                f"{self.catalog_url}/removeRoom",
                params={"bedroom_id": bedroom_id},
                timeout=5
            )
            res.raise_for_status()
            logger.info(f"Successfully removed bedroom {bedroom_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing bedroom {bedroom_id}: {e}")
            return False

    def _check_room(self, chat_ID, room_id, password):
        """Check if a room exists and password is correct."""
        params = {"bedroom_id": room_id, "password": password}
        data = self._request_catalog("get", "checkRoom", chat_ID, params=params)
        return data is not None

    def _check_username_exists(self, chat_ID, username):
        """Check if a username already exists in the Catalog."""
        data = self._request_catalog("get", "checkUsername", chat_ID, params={"username": username})
        if data and data.get("exists"):
            self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another one.")
            return True
        return False

    def _add_user(self, chat_ID, username, bedroom_id):
        """Add a new user to the Catalog."""
        user = {"username": username, "telegram_chat_id": chat_ID, "bedroom_id": bedroom_id}
        data = self._request_catalog("post", "addUser", chat_ID, json=user)
        return data is not None

#####################################################################
#   Registering of the service in the Catalog and background loop to update last_update
#####################################################################
    def register_service(self):
        service = {
            "serviceID": self.service_info['serviceID'],
            "name": self.service_info['name'],
            "endpoint": f"http://{self.service_info['host']}:{self.service_info['port']}",
            "type": self.service_info.get('type', 'TelegramBot'),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            response = requests.post(f'{self.catalog_url}/addService', json=service, timeout=5)
            response.raise_for_status()
            logger.info('Successfully registered with Catalog')
        except requests.exceptions.Timeout:
            logger.error('Timeout registering service with Catalog')
        except requests.exceptions.HTTPError as e:
            logger.error(f'HTTP error registering service: {e}')
        except Exception as e:
            logger.error(f'Registration failed: {e}')

    def update_service(self):
        service = {
            "serviceID": self.service_info['serviceID'],
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            response = requests.put(f'{self.catalog_url}/updateServiceLastUpdate', json=service, timeout=5)
            response.raise_for_status()
            logger.debug('Successfully updated service with Catalog')
        except requests.exceptions.Timeout:
            logger.warning('Timeout updating service with Catalog')
        except requests.exceptions.HTTPError as e:
            logger.error(f'HTTP error updating service: {e}')
        except Exception as e:
            logger.error(f'Update failed: {e}')

    def unregister_service(self):
        try:
            response = requests.delete(
                f'{self.catalog_url}/removeService',
                params={'serviceID': self.service_info['serviceID']},
                timeout=5
            )
            response.raise_for_status()
            logger.info('Successfully unregistered service from Catalog')
        except requests.exceptions.Timeout:
            logger.error('Timeout unregistering service from Catalog')
        except requests.exceptions.HTTPError as e:
            logger.error(f'HTTP error unregistering service: {e}')
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
        if self._worker is not None:
            self._worker.join(timeout=2)
            self._worker = None


if __name__ == "__main__":
    with open("conf.json", "r") as f:
        full_conf = json.load(f)

    conf = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}

    telegram_bot = TelegramBot(full_conf)
    cherrypy.tree.mount(telegram_bot, '/', conf)
    cherrypy.config.update({
        'server.socket_host': full_conf['serviceInfo']['host'],
        'server.socket_port': full_conf['serviceInfo']['port']
    })

    cherrypy.engine.subscribe('start', telegram_bot.start_background_loop)
    cherrypy.engine.subscribe('stop', telegram_bot.stop_background_loop)
    cherrypy.engine.subscribe('stop', telegram_bot.unregister_service)

    cherrypy.engine.start()
    cherrypy.engine.block()