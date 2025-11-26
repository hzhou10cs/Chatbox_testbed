import os
import json
import hashlib
from datetime import date
from datetime import datetime

BASE_DIR = "user_data"
USERS_DB_PATH = os.path.join(BASE_DIR, "users_db.json")


def ensure_base_dir() -> None:
    """Ensure that the base data directory exists."""
    os.makedirs(BASE_DIR, exist_ok=True)


def load_json(path: str, default):
    """Load JSON from a file, returning default on error or if the file does not exist."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data) -> None:
    """Save JSON to a file, creating parent directories if necessary."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def hash_pw(password: str) -> str:
    """Return a SHA256 hash of the given password string."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def today_str() -> str:
    """Return today's date as an ISO string (YYYY-MM-DD)."""
    return date.today().isoformat()


def get_user_dir(username: str) -> str:
    """Return the directory for a given user, creating it if necessary."""
    directory = os.path.join(BASE_DIR, username)
    os.makedirs(directory, exist_ok=True)
    return directory


def get_user_file(username: str, filename: str) -> str:
    """Return a path inside the user's directory."""
    return os.path.join(get_user_dir(username), filename)

def compute_plan_position(user_info_state: dict, today_str: str) -> tuple[int, int, int]:
    """
    Compute 12-week plan position given:
    - register_date_str: "YYYY-MM-DD"
    - today_str:         "YYYY-MM-DD" (from today_str())

    Returns:
        (plan_day_index, week_index, day_in_week), all 1-based.
        Example: (10, 2, 3) -> Day 10, Week 2, Day 3 of that week.
    """
    register_date_str = user_info_state.get("register_date")
    try:
        reg_date = datetime.strptime(register_date_str, "%Y-%m-%d").date()
        today = datetime.strptime(today_str, "%Y-%m-%d").date()
    except Exception:
        # Fallback: if parsing fails, treat today as day 1
        return 1, 1, 1

    delta_days = (today - reg_date).days
    if delta_days < 0:
        delta_days = 0

    plan_day = delta_days + 1  # 注册当天为 Day 1
    week = (plan_day - 1) // 7 + 1
    day_in_week = (plan_day - 1) % 7 + 1
    return plan_day, week, day_in_week