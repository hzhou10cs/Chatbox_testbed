from typing import Dict, Any
import json

from storage import get_user_file, load_json, save_json, today_str
from agents.prompt_helper import apply_delta_text, state_to_text


def load_goals_data(username: str) -> Dict[str, Any]:
    """
    Load all goals for a given user from goals.json.
    Structure: { "YYYY-MM-DD": { "summary": str, "feedback": str }, ... }
    """
    path = get_user_file(username, "goals.json")
    return load_json(path, {})


def save_goals_data(username: str, data: Dict[str, Any]) -> None:
    """
    Overwrite the user's goals.json with the given data dict.
    """
    path = get_user_file(username, "goals.json")
    save_json(path, data)


def _load_state_from_summary(summary_text: str) -> Dict[str, Any]:
    """
    Try to interpret an existing summary string as JSON state.
    If parsing fails, return empty dict.
    """
    if not summary_text:
        return {}
    try:
        return json.loads(summary_text)
    except Exception:
        return {}

def save_extractor_summary(username: str, date_str: str, extractor_output: str) -> None:
    """
    Save the extractor's delta output into goals.json under this date,
    using prompt_helper_b's fixed STATE schema.
    """
    goals = load_goals_data(username)
    entry = goals.get(date_str, {})

    old_summary = entry.get("summary", "")
    old_state = _load_state_from_summary(old_summary)

    try:
        new_state = apply_delta_text(old_state, extractor_output)
        summary_text = state_to_text(new_state)
    except Exception:
        summary_text = extractor_output

    entry["summary"] = summary_text
    entry.setdefault("feedback", "")
    goals[date_str] = entry
    save_goals_data(username, goals)


def load_latest_goal_action(user_state):
    """
    Core logic: load the most recent goal entry for the current user.

    """
    if not user_state.get("logged_in"):
        return "", "", "Please log in first."

    username = user_state.get("username")
    goals = load_goals_data(username)

    if not goals:
        today = today_str()
        empty_state_json = state_to_text({})
        goals[today] = {
            "summary": empty_state_json,
            "feedback": "",
        }
        save_goals_data(username, goals)
        date_label = f"Date: {today}"
        return empty_state_json, "", date_label

    latest_date = sorted(goals.keys())[-1]
    entry = goals.get(latest_date, {})
    summary = entry.get("summary", "")
    feedback = entry.get("feedback", "")

    if not summary:
        summary = state_to_text({})
        entry["summary"] = summary
        goals[latest_date] = entry
        save_goals_data(username, goals)

    date_label = f"Date: {latest_date}"
    return summary, feedback, date_label


def save_goal_feedback_action(
    user_state,
    summary_text: str,
    feedback_text: str,
    date_label: str,
):
    """
    Save user feedback for the currently displayed goal date.
    """
    if not user_state.get("logged_in"):
        return "Please log in first."

    # 从 "Date: YYYY-MM-DD" 提取日期；如果失败就默认今天
    if ":" in date_label:
        _, _, tail = date_label.partition(":")
        date_str = tail.strip()
    else:
        date_str = today_str()

    username = user_state.get("username")
    goals = load_goals_data(username)

    entry = goals.get(date_str, {})

    if summary_text:
        entry["summary"] = summary_text
    else:
        entry.setdefault("summary", state_to_text({}))

    entry["feedback"] = feedback_text or ""
    goals[date_str] = entry
    save_goals_data(username, goals)

    return (
        f"Feedback for {date_str} has been saved. "
        "It will be used as part of future prompts for the agent."
    )


def load_goal_summary_for_ui(user_state):
    """
    Small wrapper used by app.py:

    Returns:
        summary_text: str 
        feedback_text: str
        date_label:   str
        status_msg:   str
    """
    summary, feedback, date_label = load_latest_goal_action(user_state)

    if not user_state.get("logged_in"):
        return "", "", "", "Please log in first."

    return summary, feedback, date_label, ""