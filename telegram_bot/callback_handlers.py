class CallbackHandlers:
    def __init__(self, bot):
        self._bot = bot

    def handle_create_room(self, chat_ID):
        if not self._bot.require_username(chat_ID):
            return
        self._bot.reset_bedroom_info(chat_ID)
        self._bot.bot.sendMessage(chat_ID, "📝 Let's create a new room — what's the room name? (e.g. 'Bedroom')")
        self._bot.set_state(chat_ID, "waiting_room_name")

    def handle_view_data(self, chat_ID):
        self._bot.refresh_bedroom_info(chat_ID)
        room_name = self._bot.get_bedroom_info(chat_ID, "room_name") or "N/A"
        bedtime = self._bot.get_bedroom_info(chat_ID, "bedtime") or "N/A"
        wakeup = self._bot.get_bedroom_info(chat_ID, "wakeup") or "N/A"
        desired_temp = self._bot.get_bedroom_info(chat_ID, "desired_temp") or "N/A"
        self._bot.bot.sendMessage(
            chat_ID,
            f"""
        <b>ROOM DATA 🛌</b>

    <b>🏷️ Name:</b> {room_name}
    <b>🛌 Bedtime:</b> {bedtime}
    <b>⏰ Wake-up:</b> {wakeup}
    <b>🌡️ Temperature:</b> {desired_temp}°C
        """,
            parse_mode="HTML"
        )
        self._bot.send_room_data_options(chat_ID)

    def handle_manage_settings(self, chat_ID):
        self._bot.send_room_settings_options(chat_ID)

    def handle_manage_devices(self, chat_ID):
        self._bot.send_device_management_options(chat_ID)

    def handle_list_devices(self, chat_ID):
        self._bot.show_devices(chat_ID)

    def handle_delete_room(self, chat_ID):
        self._bot.bot.sendMessage(chat_ID, "⚠️ Are you sure you want to delete the room? Type 'yes' to confirm. This action cannot be undone.")
        self._bot.set_state(chat_ID, "waiting_delete_confirmation")

    def handle_view_sensor_data(self, chat_ID):
        self._bot.bot.sendMessage(chat_ID, "🔎 Sensor data — feature not implemented yet. We're working on it! 🚧")


    def handle_view_sleep_quality(self, chat_ID):
        self._bot.bot.sendMessage(chat_ID, "💤 Sleep quality — feature not implemented yet. Stay tuned! ✨")

    def handle_main_menu(self, chat_ID):
        self._bot.send_registered_user_options(chat_ID)

    def handle_add_device(self, chat_ID, device_type=None):
        if device_type not in ("light", "heater", "fan"):
            self._bot.bot.sendMessage(chat_ID, "❌ Unsupported device type.")
            return
        self._bot.set_state(chat_ID, "waiting_add_device_name", pending_device_type=device_type)
        self._bot.bot.sendMessage(chat_ID, f"➕ Great — what should we call the {device_type} device? Send a short name. 🏷️")

    def handle_remove_device(self, chat_ID):
        self._bot.begin_remove_device(chat_ID)
