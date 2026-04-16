import curses
import sys

import requests

from common_simulation import get_user_service_endpoint
from night_simulation import DEFAULT_DURATION_SECONDS, load_test_config, run_simulation


def fetch_active_users(config):
    catalog_url = config["catalog"]["url"]
    user_service_url = get_user_service_endpoint(catalog_url)

    users_res = requests.get(f"{user_service_url}/getAllUsers", timeout=5)
    users_res.raise_for_status()
    users = users_res.json().get("users", [])

    active_res = requests.get(f"{user_service_url}/getActiveRoomsWithUser", timeout=5)
    active_res.raise_for_status()
    active_rooms = active_res.json().get("active_rooms", {}) or {}

    active_users = []
    for user in users:
        user_id = str(user.get("id", "")).strip()
        room_id = active_rooms.get(user_id)
        if room_id is None:
            room_id = active_rooms.get(int(user_id)) if user_id.isdigit() else None
        if room_id is None:
            continue
        active_users.append(
            {
                "id": user_id,
                "email": user.get("email", f"User {user_id}"),
                "room_id": str(room_id),
            }
        )

    active_users.sort(key=lambda user: user["email"].lower())
    return active_users


def _draw_picker(stdscr, users, cursor, selected_ids):
    stdscr.erase()
    stdscr.addstr(0, 0, "Select active users for Test Sleep Cycle")
    stdscr.addstr(1, 0, "Use Up/Down, Space to toggle, Enter to confirm.")

    for index, user in enumerate(users):
        marker = "[x]" if user["id"] in selected_ids else "[ ]"
        prefix = "> " if index == cursor else "  "
        line = f"{prefix}{marker} {user['email']}  (user {user['id']}, room {user['room_id']})"
        stdscr.addstr(index + 3, 0, line)

    stdscr.refresh()


def choose_users(users):
    if not users:
        raise RuntimeError("No active users found.")

    def _picker(stdscr):
        curses.curs_set(0)
        cursor = 0
        selected_ids = {users[0]["id"]}

        while True:
            _draw_picker(stdscr, users, cursor, selected_ids)
            key = stdscr.getch()

            if key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % len(users)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % len(users)
            elif key == ord(" "):
                user_id = users[cursor]["id"]
                if user_id in selected_ids:
                    if len(selected_ids) > 1:
                        selected_ids.remove(user_id)
                else:
                    selected_ids.add(user_id)
            elif key in (10, 13, curses.KEY_ENTER):
                return [user["id"] for user in users if user["id"] in selected_ids]

    return curses.wrapper(_picker)


def prompt_date():
    default_date = "2026-03-20"
    date_value = input(f"Enter the night base date in YYYY-MM-DD format [{default_date}]: ").strip()
    return date_value or default_date


def main():
    try:
        config = load_test_config()
        active_users = fetch_active_users(config)
        selected_user_ids = choose_users(active_users)
    except Exception as exc:
        print(f"Unable to fetch/select active users: {exc}", file=sys.stderr)
        raise SystemExit(1)

    target_date = prompt_date()
    run_simulation(
        duration_seconds=DEFAULT_DURATION_SECONDS,
        target_date=target_date,
        selected_user_ids=selected_user_ids,
    )


if __name__ == "__main__":
    main()
