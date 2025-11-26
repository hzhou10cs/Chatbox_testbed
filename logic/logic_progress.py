from datetime import datetime, timedelta
from typing import Dict, Any

from storage import get_user_file, load_json, save_json


def compute_date_for_week_day(register_date_str: str, week: int, day: int):
    """Compute the absolute date for a given week/day since registration."""
    if not register_date_str:
        return None
    try:
        d0 = datetime.fromisoformat(register_date_str).date()
    except Exception:
        return None
    offset = (week - 1) * 7 + (day - 1)
    return d0 + timedelta(days=offset)


def load_progress_data(username: str) -> Dict[str, Any]:
    path = get_user_file(username, "progress.json")
    return load_json(path, {})


def save_progress_data(username: str, data: Dict[str, Any]) -> None:
    path = get_user_file(username, "progress.json")
    save_json(path, data)


def load_progress_action(week: str, day: str, user_state: Dict[str, Any]):
    """Gradio callback: load or create progress entry for a specific week/day."""
    if not user_state.get("logged_in"):
        return "", "", "", "Please log in first."

    username = user_state.get("username")
    info_path = get_user_file(username, "user_info.json")
    info = load_json(info_path, {})
    reg_date = info.get("register_date")
    if not reg_date:
        return "", "", "", "Registration date not found. Please check profile information."

    try:
        w = int(week)
        d = int(day)
    except Exception:
        return "", "", "", "Please select a valid week and day."

    abs_date = compute_date_for_week_day(reg_date, w, d)
    if not abs_date:
        return "", "", "", "Failed to compute absolute date. Please check registration date."

    date_str = abs_date.isoformat()
    progress_data = load_progress_data(username)
    entry = progress_data.get(date_str, {})

    weight_today = entry.get("weight_today", "")
    notes = entry.get("notes", "")

    msg = f"Date: {date_str}"
    if entry:
        msg += " (loaded existing record)"
    else:
        msg += " (no record yet, you can create one)"

    return date_str, weight_today, notes, msg


def save_progress_action(
    week: str,
    day: str,
    date_str: str,
    weight_today: str,
    notes: str,
    user_state: Dict[str, Any],
):
    """Gradio callback: save progress information for a given day."""
    if not user_state.get("logged_in"):
        return "Please log in first."

    username = user_state.get("username")
    info_path = get_user_file(username, "user_info.json")
    info = load_json(info_path, {})
    reg_date = info.get("register_date")
    if not reg_date:
        return "Registration date not found. Cannot save progress."

    try:
        w = int(week)
        d = int(day)
    except Exception:
        return "Please select a valid week and day."

    if not date_str:
        abs_date = compute_date_for_week_day(reg_date, w, d)
        if not abs_date:
            return "Failed to compute absolute date. Please check registration date."
        date_str = abs_date.isoformat()

    progress_data = load_progress_data(username)
    progress_data[date_str] = {
        "week": w,
        "day": d,
        "weight_today": weight_today or "",
        "notes": notes or "",
    }
    save_progress_data(username, progress_data)

    return f"Progress saved for {date_str} (week {w}, day {d})."
