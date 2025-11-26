import os
import json
import hashlib
from datetime import date

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
