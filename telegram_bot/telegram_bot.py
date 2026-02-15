import json
import os
import time
import threading
from datetime import datetime

import cherrypy
from dotenv import load_dotenv
import requests
from requests import HTTPError
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
            if chat_ID not in self.chatIDs:
                self.chatIDs.append(chat_ID)
            self.bot.sendMessage(chat_ID, text="Welcome to BetterSleep User Bot! Use /help to see available commands.")
            self.send_room_options(chat_ID)
            return

        elif message == "/help":
            self.bot.sendMessage(chat_ID,
                                 text="Available commands:\n/start - Start the bot\n/help - Show this help message")
            return

        state_info = self.user_states.get(chat_ID)

        if state_info:
            curr_state = state_info.get("state")

            if curr_state == "waiting_room_name":
                self.user_states[chat_ID]["room_name"] = message
                self.user_states[chat_ID]["state"] = "waiting_room_password"
                self.bot.sendMessage(chat_ID, f"Room '{message}' set. Now enter the password:")

            elif curr_state == "waiting_room_password":
                room_name = self.user_states[chat_ID]["room_name"]
                password = message

                bedroom = {
                    "room_name": room_name,
                    "password": password
                }

                try:
                    res = requests.post(f"{self.catalog_url}/addBedroom", json=bedroom)
                    if res.status_code == 200:
                        # Assumiamo che il server ritorni JSON con il nuovo bedroom_id
                        data = res.json()
                        room_id = data.get("bedroom_id")  # <- qui ottieni l'ID
                        self.bot.sendMessage(chat_ID, f"Successfully created room '{room_name}' with ID {room_id}!")
                    else:
                        self.bot.sendMessage(chat_ID, "Access denied: room creation failed.")
                        room_id = None
                except Exception as e:
                    self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
                    room_id = None

                if room_id:
                    self.user_states[chat_ID] = {
                        "state": "registing_user",
                        "bedroom_id": room_id
                    }
                    print(f"User {chat_ID} registered in room {room_id}")
                    self.bot.sendMessage(chat_ID, "Now enter your username to register in the room:")

            elif curr_state == "waiting_join_bedroom_id":
                self.user_states[chat_ID]["join_id"] = message
                self.user_states[chat_ID]["state"] = "waiting_join_password"
                self.bot.sendMessage(chat_ID, "Enter the password for this room:")


            elif curr_state == "waiting_join_password":
                room_id = self.user_states[chat_ID]["join_id"]
                password = message
                try:
                    res = requests.get(f"{self.catalog_url}/checkRoom",
                                       params={"bedroom_id": room_id, "password": password})
                    if res.status_code == 200:
                        self.bot.sendMessage(chat_ID, f"Successfully joined room {room_id}!")
                        self.user_states[chat_ID] = {
                            "state": "registing_user",
                            "bedroom_id": room_id
                        }
                        self.bot.sendMessage(chat_ID, "Now enter your username to register in the room:")
                    else:
                        self.bot.sendMessage(chat_ID, "Access denied: wrong ID or password.")
                        self.user_states[chat_ID] = {"state": "waiting_join_bedroom_id"}
                except requests.exceptions.RequestException as e:
                    self.bot.sendMessage(chat_ID, "Connection error with Catalog.")
                    self.user_states[chat_ID] = {"state": "waiting_join_bedroom_id"}

            elif curr_state == "registing_user":
                # Get room_id from either creating or joining a room
                bedroom_id = self.user_states[chat_ID].get("bedroom_id")
                print(bedroom_id)
                username = message
                user = {
                    "username": username,
                    "telegram_chat_id": chat_ID,
                    "bedroom_id": bedroom_id
                }
                try:
                    res = requests.get(f"{self.catalog_url}/checkUsername",
                                        params={"username": username})
                    if res.status_code == 200 and res.json().get("exists"):
                            self.bot.sendMessage(chat_ID, f"Username '{username}' already exists. Please choose another one.")
                            return

                    res = requests.post(f"{self.catalog_url}/addUser", json=user)
                    if res.status_code == 200:
                        self.bot.sendMessage(chat_ID, f"Successfully registered as '{username}' in room {bedroom_id}!")
                    elif res.status_code == 409:
                        self.bot.sendMessage(chat_ID, f"Error You are already registered in a room")
                except Exception as e:
                    self.bot.sendMessage(chat_ID, "Connection error with Catalog.")

    def send_room_options(self, chat_ID):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Create a room", callback_data="create_room")],
            [InlineKeyboardButton(text="🚪 Join a room", callback_data="join_room")]
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