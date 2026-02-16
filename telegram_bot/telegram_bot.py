import json
import os
import time
import threading
from datetime import datetime

import cherrypy
from dotenv import load_dotenv
import requests
import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardButton, InlineKeyboardMarkup


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
        self.bot = telepot.Bot(self.token)
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
            self._send_help(chat_ID)
            return

        state_info = self.user_states.get(chat_ID)
        if not state_info:
            return

        curr_state = state_info.get("state")
        self._dispatch_state(chat_ID, curr_state, message)

    def _handle_start(self, chat_ID):
        if chat_ID not in self.chatIDs:
            self.chatIDs.append(chat_ID)
        self.bot.sendMessage(chat_ID, text="Welcome to BetterSleep! Use /help to see available commands.")
        self._handel_restore_user_session(chat_ID)
        if self.user_states.get(chat_ID, {}).get("state") != "registered":
            self.send_room_options(chat_ID)
        else:
            self.send_registered_user_options(chat_ID)

    def _send_help(self, chat_ID):
        self.bot.sendMessage(chat_ID,
                             text="Available commands:\n/start - Start the bot\n/help - Show this help message")

    def _dispatch_state(self, chat_ID, curr_state, message):
        handlers = {
            "waiting_room_name": self._handle_waiting_room_name,
            "waiting_room_password": self._handle_waiting_room_password,
            "waiting_join_bedroom_id": self._handle_waiting_join_bedroom_id,
            "waiting_join_password": self._handle_waiting_join_password,
            "registing_user": self._handle_registing_user,
            "registered": self._handle_registered_user
        }
        handler = handlers.get(curr_state)
        if handler:
            handler(chat_ID, message)


    def _handle_registered_user(self, chat_ID, message):
        username = self.user_states[chat_ID].get("username", "User")
        bedroom_id = self.user_states[chat_ID].get("bedroom_id", "N/A")
        # se e giorno invia Good morning, altrimenti Good evening
        #!TODO Implement this


    def _handle_waiting_room_name(self, chat_ID, message):
        self.user_states[chat_ID]["room_name"] = message
        self.user_states[chat_ID]["state"] = "waiting_room_password"
        self.bot.sendMessage(chat_ID, f"Room '{message}' set. Now enter the password:")

    def _handel_restore_user_session(self, chat_ID):
        try:
            res = requests.get(f"{self.catalog_url}/getUserSession", params={"telegram_chat_id": chat_ID})
            if res.status_code == 200:
                data = res.json()
                username = data.get("username")
                bedroom_id = data.get("bedroom_id")
                self.user_states[chat_ID] = {
                    "state": "registered",
                    "bedroom_id": bedroom_id,
                    "username": username
                }
                self.bot.sendMessage(chat_ID, f"Welcome back, {username} from room {bedroom_id}!")
            else:
                username = ""
                bedroom_id = ""
        except requests.exceptions.RequestException:
            self.bot.sendMessage(chat_ID, "Connection error with Catalog. Unable to restore session.")

    def _handle_waiting_room_password(self, chat_ID, message):
        room_name = self.user_states[chat_ID]["room_name"]
        room_id = self._create_bedroom(chat_ID, room_name, message)
        if room_id:
            self.user_states[chat_ID] = {
                "state": "registing_user",
                "bedroom_id": room_id
            }
            print(f"User {chat_ID} registered in room {room_id}")
            self.bot.sendMessage(chat_ID, "Now enter your username to register in the room:")

    def _handle_waiting_join_bedroom_id(self, chat_ID, message):
        self.user_states[chat_ID]["bedroom_id"] = message
        self.user_states[chat_ID]["state"] = "waiting_join_password"
        self.bot.sendMessage(chat_ID, "Enter the password for this room:")

    def _handle_waiting_join_password(self, chat_ID, message):
        room_id = self.user_states[chat_ID]["bedroom_id"]
        if self._check_room(chat_ID, room_id, message):
            self.bot.sendMessage(chat_ID, f"Successfully joined room {room_id}!")
            self.user_states[chat_ID] = {
                "state": "registing_user",
                "bedroom_id": room_id
            }
            self.bot.sendMessage(chat_ID, "Now enter your username to register in the room:")
        else:
            self.user_states[chat_ID] = {"state": "waiting_join_bedroom_id"}

    def _handle_registing_user(self, chat_ID, message):
        bedroom_id = self.user_states[chat_ID].get("bedroom_id")
        print(bedroom_id)
        username = message
        if self._check_username_exists(chat_ID, username):
            return
        if self._add_user(chat_ID, username, bedroom_id):
            if 6 <= datetime.now().hour < 18:
                greeting = "Good morning"
            else:
                greeting = "Good evening"
            self.bot.sendMessage(chat_ID,
                                 f"{greeting}, {username} from room {bedroom_id}! You can use the following commands:")
            self.user_states[chat_ID] = {
                "state": "registered",
                "bedroom_id": bedroom_id,
                "username": username
            }

    def _create_bedroom(self, chat_ID, room_name, password):
        bedroom = {
            "room_name": room_name,
            "password": password
        }
        try:
            res = requests.post(f"{self.catalog_url}/addBedroom", json=bedroom)
            if res.status_code == 200:
                data = res.json()
                room_id = data.get("bedroom_id")
                self.bot.sendMessage(chat_ID, f"Successfully created room '{room_name}' with ID {room_id}!")
                return room_id
            self.bot.sendMessage(chat_ID, "Access denied: room creation failed.")
        except requests.exceptions.RequestException:
            self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
        return None

    def _check_room(self, chat_ID, room_id, password):
        try:
            res = requests.get(f"{self.catalog_url}/checkRoom",
                               params={"bedroom_id": room_id, "password": password})
            if res.status_code == 200:
                return True
            self.bot.sendMessage(chat_ID, "Access denied: wrong ID or password.")
        except requests.exceptions.RequestException:
            self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
        return False

    def _check_username_exists(self, chat_ID, username):
        try:
            res = requests.get(f"{self.catalog_url}/checkUsername",
                               params={"username": username})
            if res.status_code == 200 and res.json().get("exists"):
                self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another one.")
                return True
        except requests.exceptions.RequestException:
            self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
            return True
        return False

    def _add_user(self, chat_ID, username, bedroom_id):
        user = {
            "username": username,
            "telegram_chat_id": chat_ID,
            "bedroom_id": bedroom_id
        }
        try:
            res = requests.post(f"{self.catalog_url}/addUser", json=user)
            if res.status_code == 200:
                self.bot.sendMessage(chat_ID, f"Successfully registered as '{username}' in room {bedroom_id}!")
                return True
            if res.status_code == 409:
                self.bot.sendMessage(chat_ID, "Error You are already registered in a room")
                #!TODO need to find the way to get the username and room_id of the user to update the state
                self.user_states [chat_ID] = {"state": "registered", "bedroom_id": None, "username": None}
                return True
        except requests.exceptions.RequestException:
            self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
        return False

    def send_room_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Create a room", callback_data="create_room")],
            [InlineKeyboardButton(text="🚪 Join a room", callback_data="join_room")]
        ])
        self.bot.sendMessage(chat_ID, text="What would you like to do?", reply_markup=keyboard)
    def send_registered_user_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 View room data", callback_data="view_data")],
            [InlineKeyboardButton(text="⚙️ Manage room settings", callback_data="manage_settings")]
        ])
        self.bot.sendMessage(chat_ID, text="What would you like to do?", reply_markup=keyboard)
    def on_callback_query(self, msg):
        query_ID, from_ID, query_data = telepot.glance(msg, flavor='callback_query')
        self.bot.answerCallbackQuery(query_ID)

        if query_data == "create_room":
            self.bot.sendMessage(from_ID, text="You chose to create a room. Please enter the name of the room:")
            self.user_states[from_ID] = {"state": "waiting_room_name"}

        elif query_data == "join_room":
            self.bot.sendMessage(from_ID, text="You chose to join a room. Please enter the ID of the bedroom:")
            self.user_states[from_ID] = {"state": "waiting_join_bedroom_id"}

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
        except Exception as e:
            print(f'Registration failed: {e}')

    def update_service(self):
        service = {
            "serviceID": self.service_info['serviceID'],
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            response = requests.put(f'{self.catalog_url}/updateServiceLastUpdate', json=service, timeout=5)
            response.raise_for_status()
        except Exception as e:
            print(f'Update failed: {e}')

    def unregister_service(self):
        try:
            response = requests.delete(
                f'{self.catalog_url}/removeService',
                params={'serviceID': self.service_info['serviceID']},
                timeout=5
            )
            response.raise_for_status()
        except Exception as e:
            print(f'Unregister failed: {e}')

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