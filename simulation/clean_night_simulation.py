import argparse
from datetime import timedelta

from night_simulation import (
    build_user_contexts,
    build_sleep_windows,
    default_night_bases,
    delete_previous_simulation_data,
    load_test_config,
    normalize_target_date,
)


def clean_night_simulation(target_date):
    config = load_test_config()
    user_contexts = build_user_contexts(config)
    normalized_target_date = normalize_target_date(target_date)
    bases = default_night_bases(normalized_target_date)

    if not normalized_target_date:
        raise ValueError("A target date in YYYY-MM-DD format is required.")

    if not user_contexts:
        print("No users found to clean.")
        return

    date_str = normalized_target_date.strftime("%Y-%m-%d")
    print(f"Cleaning night simulation data for {date_str}...")

    for user_ctx in user_contexts:
        windows = build_sleep_windows(user_ctx.night_time, user_ctx.morning_time, bases)
        for window in windows:
            start_time = window.sim_start.timestamp()
            end_time = (window.sim_start + timedelta(minutes=window.sim_minutes)).timestamp()
            delete_previous_simulation_data(
                config,
                user_ctx.userid,
                user_ctx.bedroomid,
                date_str,
                start_time,
                end_time,
            )

    print("Night simulation cleanup completed.")


def main():
    parser = argparse.ArgumentParser(description="Clean night simulation data for a given date")
    parser.add_argument(
        "--target-date",
        dest="target_date",
        required=True,
        help="Night base date in YYYY-MM-DD format",
    )
    args = parser.parse_args()
    clean_night_simulation(args.target_date)


if __name__ == "__main__":
    main()
