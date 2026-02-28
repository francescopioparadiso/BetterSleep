from utils import parse_time


class StateHandlers:
    """
    This class is instantiated with the main TelegramBot instance and
    delegates calls to it for shared operations (catalog calls, sending messages, state helpers).
    """

    def __init__(self, bot):
        # bot is the TelegramBot instance
        self._bot = bot

    def handle_start(self, chat_ID):
        if chat_ID not in self._bot.chatIDs:
            self._bot.chatIDs.append(chat_ID)

        self._bot.restore_user_session(chat_ID)
        state = self._bot.get(chat_ID, "state")

        if state == "registered":
            self._bot.send_registered_user_options(chat_ID)
            return
        if state:
            return

        # fresh user
        self._bot.bot.sendMessage(chat_ID, "👋 Welcome to BetterSleep — your sleep-friendly assistant! Type /help for tips.")
        self._bot.bot.sendMessage(chat_ID, "To get started, please choose a username:")
        self._bot.set_state(chat_ID, "waiting_username", username=None)

    def handle_help(self, chat_ID):
        self._bot.bot.sendMessage(chat_ID, "🤖 Available commands:\n/start - Start the bot and register\n/help - Show this help message")

    def handle_waiting_username(self, chat_ID, message):
        username = message.strip()
        if self._bot.check_username_exists(chat_ID, username):
            self._bot.bot.sendMessage(chat_ID, "❗ That username is already taken. Please choose a different one:")
            return

        payload = {"username": username, "telegram_chat_id": chat_ID, "bedroom_id": None}
        data, status, error = self._bot.catalog.post("addUser", json=payload)
        if error:
            self._bot.bot.sendMessage(chat_ID, f"❌ Could not create your account: {error}")
            return

        self._bot.set_state(chat_ID, "waiting_room_name", username=username)
        self._bot.bot.sendMessage(chat_ID, f"🎉 Nice to meet you, {username}! Let's set up your personal room. What's the room name? Send 'skip' to use a default name.")

    def handle_waiting_room_name(self, chat_ID, message):
        if not self._bot.require_username(chat_ID):
            return

        room_name = message.strip()
        if room_name.lower() == 'skip' or room_name == '':
            room_name = f"{self._bot.get(chat_ID, 'username')}'s room"

        # room_name is the single shared field — used both during wizard and in settings display
        self._bot.set_bedroom_info(chat_ID, room_name=room_name)
        self._bot.set_state(chat_ID, "waiting_room_bedtime")
        self._bot.bot.sendMessage(chat_ID, "🕰️ What's your usual bedtime? Reply in HH:MM (24h), e.g. 23:00")

    def handle_waiting_room_bedtime(self, chat_ID, message):
        bedtime = parse_time(message)
        if not bedtime:
            self._bot.bot.sendMessage(chat_ID, "❗ Invalid time format. Please use HH:MM, e.g. 23:00")
            return
        self._bot.set_bedroom_info(chat_ID, bedtime=bedtime)
        self._bot.set_state(chat_ID, "waiting_room_wakeup")
        self._bot.bot.sendMessage(chat_ID, "⏰ Now send your usual wakeup time in HH:MM, e.g. 07:00")

    def handle_waiting_room_wakeup(self, chat_ID, message):
        wakeup = parse_time(message)
        if not wakeup:
            self._bot.bot.sendMessage(chat_ID, "❗ Invalid time format. Please use HH:MM, e.g. 07:00")
            return
        self._bot.set_bedroom_info(chat_ID, wakeup=wakeup)
        self._bot.set_state(chat_ID, "waiting_room_temp")
        self._bot.bot.sendMessage(chat_ID, "🌡️ Finally, what's your desired bedroom temperature? Send a number, e.g. 21.5")

    def handle_waiting_room_temp(self, chat_ID, message):
        try:
            temp = float(message.strip())
        except ValueError:
            self._bot.bot.sendMessage(chat_ID, "❗ Invalid temperature. Please send a number, e.g. 22 or 21.5")
            return
        if temp < 5 or temp > 35:
            self._bot.bot.sendMessage(chat_ID, "⚠️ Please choose a temperature between 5 and 35 °C.")
            return

        self._bot.set_bedroom_info(chat_ID, desired_temp=temp)

        # collect all bedroom_info fields and create the room
        room_name    = self._bot.get_bedroom_info(chat_ID, "room_name")
        bedtime      = self._bot.get_bedroom_info(chat_ID, "bedtime")
        wakeup       = self._bot.get_bedroom_info(chat_ID, "wakeup")
        desired_temp = self._bot.get_bedroom_info(chat_ID, "desired_temp")
        username     = self._bot.get(chat_ID, "username")

        self._bot.bot.sendMessage(
            chat_ID,
            f"🔨 Creating room '{room_name}' — bedtime {bedtime}, wakeup {wakeup}, temp {desired_temp}°C…"
        )
        room_id = self._bot.create_bedroom(chat_ID, room_name, bedtime=bedtime, wakeup=wakeup, desired_temperature=desired_temp)

        if not room_id:
            self._bot.bot.sendMessage(chat_ID, "❌ Couldn't create the room right now. Let's try again — what's the room name?")
            self._bot.reset_bedroom_info(chat_ID)
            self._bot.set_state(chat_ID, "waiting_room_name")
            return

        assoc_data, assoc_status, assoc_error = self._bot.catalog.post("associateUserToBedroom", json={"telegram_chat_id": chat_ID, "bedroom_id": room_id})
        if not assoc_error and assoc_data and assoc_data.get("status") == "success":
            self._bot.finalize_registration(chat_ID, username, room_id)
        else:
            self._bot.bot.sendMessage(chat_ID, f"❌ Could not associate the room to your user: {assoc_error or 'Unknown error'}")
            try:
                self._bot.catalog.delete("removeRoom", params={"bedroom_id": room_id})
            except Exception:
                pass
            self._bot.reset_bedroom_info(chat_ID)
            self._bot.set_state(chat_ID, "waiting_room_name")

    def handle_delete_room(self, chat_ID, message):
        if message.lower() != "yes":
            self._bot.bot.sendMessage(chat_ID, "✅ Room deletion cancelled. No changes made.")
            self._bot.send_registered_user_options(chat_ID)
            return

        bedroom_id = self._bot.get(chat_ID, "bedroom_id")
        self._bot.remove_bedroom(bedroom_id)
        self._bot.bot.sendMessage(chat_ID, f"🗑️ Room {bedroom_id} deleted.")
        self._bot.ensure_valid_state_and_show_menu(chat_ID)

    def handle_waiting_remove_device_choice(self, chat_ID, message):
        if not message.strip().isdigit():
            self._bot.bot.sendMessage(chat_ID, "❗ Please send a valid number (e.g., 0, 1, 2).")
            return
        idx = int(message.strip())
        devices = self._bot.get_bedroom_info(chat_ID, "devices_list") or []
        if idx < 0 or idx >= len(devices):
            self._bot.bot.sendMessage(chat_ID, "❗ Number out of range. Please try again.")
            return

        device_id = devices[idx].get('device_id')
        data, status, error = self._bot.catalog.delete("removeDevice", params={"deviceID": device_id})
        if error:
            self._bot.bot.sendMessage(chat_ID, f"❌ Failed to remove device {device_id}: {error}")
        else:
            self._bot.bot.sendMessage(chat_ID, f"✅ Device {device_id} removed.")

        self._bot.set_bedroom_info(chat_ID, devices_list=None)
        self._bot.ensure_valid_state_and_show_menu(chat_ID)

    def handle_waiting_add_device_name(self, chat_ID, message):
        name = message.strip()
        if not name:
            self._bot.bot.sendMessage(chat_ID, "❗ Please send a non-empty name for the device.")
            return
        if len(name) > 64:
            self._bot.bot.sendMessage(chat_ID, "❗ Please choose a shorter name (max 64 characters).")
            return

        pending_type = self._bot.get(chat_ID, "pending_device_type")
        if not pending_type:
            self._bot.bot.sendMessage(chat_ID, "⚠️ Device type not selected. Please start again from Manage devices.")
            self._bot.ensure_valid_state_and_show_menu(chat_ID)
            return

        bedroom_id = self._bot.require_bedroom(chat_ID)
        if not bedroom_id:
            self._bot.ensure_valid_state_and_show_menu(chat_ID)
            return

        payload = {
            "device_name": name,
            "device_type": pending_type,
            "bedroom_id":  bedroom_id,
            "value": 0,
        }
        self._bot.bot.sendMessage(chat_ID, f"🔧 Creating {pending_type} device named '{name}'…")
        data, status, error = self._bot.catalog.post("addDevice", json=payload)

        if error:
            self._bot.bot.sendMessage(chat_ID, f"❌ Could not create device: {error}")
        elif data and data.get("status") == "success":
            device_id = data.get("device_id") or data.get("id") or "(unknown)"
            self._bot.bot.sendMessage(chat_ID, f"✅ Device created: {name} (id: {device_id}) — added to your room.")
        else:
            self._bot.bot.sendMessage(chat_ID, "❌ Could not create device.")

        # Clear pending device type and return to main menu
        self._bot.set_state(chat_ID, "registered", pending_device_type=None)
        self._bot.send_registered_user_options(chat_ID)

    def _update_bedroom_setting(self, chat_ID, message, field_name, validator=None, display_name=None):
        """Generic method to update a bedroom setting.

        Args:
            chat_ID: Telegram chat ID
            message: User's input message
            field_name: Database field name (e.g., 'room_name', 'bedtime', 'wakeup', 'desired_temperature')
            validator: Optional function to validate and transform the input. Should return (is_valid, value_or_error_msg)
            display_name: Human-readable name for the field (for messages)
        """
        bedroom_id = self._bot.require_bedroom(chat_ID)
        if not bedroom_id:
            self._bot.ensure_valid_state_and_show_menu(chat_ID)
            return

        display_name = display_name or field_name

        # Validate input if validator provided
        if validator:
            is_valid, result = validator(message)
            if not is_valid:
                self._bot.bot.sendMessage(chat_ID, f"❗ {result}")
                return
            value = result
        else:
            value = message.strip()

        # Update via catalog API
        payload = {"bedroom_id": bedroom_id, field_name: value}
        data, status, error = self._bot.catalog.put("updateBedroomSettings", json=payload)

        if error:
            self._bot.bot.sendMessage(chat_ID, f"❌ Could not update {display_name}: {error}")
        elif data and data.get("status") == "success":
            self._bot.bot.sendMessage(chat_ID, f"✅ {display_name} updated to {value}.")
        else:
            self._bot.bot.sendMessage(chat_ID, f"❌ Could not update {display_name}.")

        self._bot.set_state(chat_ID, "registered")
        self._bot.send_registered_user_options(chat_ID)

    def handle_waiting_change_room_name(self, chat_ID, message):
        def validate_room_name(msg):
            name = msg.strip()
            if not name:
                return False, "Please send a non-empty room name."
            if len(name) > 100:
                return False, "Please choose a shorter name (max 100 characters)."
            return True, name

        self._update_bedroom_setting(chat_ID, message, "room_name", validate_room_name, "Room name")

    def handle_waiting_change_bedtime(self, chat_ID, message):
        def validate_time(msg):
            bedtime = parse_time(msg)
            if not bedtime:
                return False, "Invalid time format. Please use HH:MM, e.g. 23:00"
            return True, bedtime

        self._update_bedroom_setting(chat_ID, message, "bedtime", validate_time, "Bedtime")

    def handle_waiting_change_wakeup(self, chat_ID, message):
        def validate_time(msg):
            wakeup = parse_time(msg)
            if not wakeup:
                return False, "Invalid time format. Please use HH:MM, e.g. 07:00"
            return True, wakeup

        self._update_bedroom_setting(chat_ID, message, "wakeup", validate_time, "Wake-up time")

    def handle_waiting_change_temp(self, chat_ID, message):
        def validate_temp(msg):
            try:
                temp = float(msg.strip())
            except ValueError:
                return False, "Invalid temperature. Please send a number, e.g. 22 or 21.5"
            if temp < 5 or temp > 35:
                return False, "Please choose a temperature between 5 and 35 °C."
            return True, temp

        self._update_bedroom_setting(chat_ID, message, "desired_temperature", validate_temp, "Desired temperature")

