import os
from datetime import datetime
from typing import Dict, Any

import gradio as gr

from storage import (
    BASE_DIR,
    USERS_DB_PATH,
    ensure_base_dir,
    load_json,
    save_json,
    hash_pw,
    today_str,
    get_user_dir,
    get_user_file,
)
from .logic_progress import save_progress_data
from .logic_goals import save_goals_data
from .logic_chat import save_chats_index


def default_user_info() -> Dict[str, Any]:
    return {
        "first_name": "",
        "last_name": "",
        "gender": "",
        "occupation": "",
        "phone": "",
        "email": "",
        "height": "",
        "initial_weight": "",
        "body_measurements": "",
        "weight_statement": "",
        "allergy": "",
        "medication": "",
        "lifestyle": "",
        "medical_history": "",
        "photo_path": None,
        "register_date": None,
    }


def load_users_db() -> Dict[str, Any]:
    return load_json(USERS_DB_PATH, {})


def save_users_db(db: Dict[str, Any]) -> None:
    save_json(USERS_DB_PATH, db)


def load_user_info_dict(username: str) -> Dict[str, Any]:
    path = get_user_file(username, "user_info.json")
    info = default_user_info()
    existing = load_json(path, {})
    info.update(existing)
    return info


def save_user_info_dict(username: str, info: Dict[str, Any]) -> None:
    path = get_user_file(username, "user_info.json")
    save_json(path, info)


def get_register_date(username: str):
    info = load_user_info_dict(username)
    rd = info.get("register_date")
    if not rd:
        return None
    try:
        return datetime.fromisoformat(rd).date()
    except Exception:
        return None


# ================== Auth: login / logout / register ==================


def login_action(username, password, user_state, user_info_state):
    ensure_base_dir()
    db = load_users_db()
    if not username or not password:
        return (
            "Please enter both username and password.",
            user_state,
            user_info_state,
            gr.update(),  # login_panel unchanged
            gr.update(),  # register_panel unchanged
            gr.update(),  # main_panel unchanged
        )

    record = db.get(username)
    if not record:
        return (
            "Account does not exist. Please register first.",
            user_state,
            user_info_state,
            gr.update(),
            gr.update(),
            gr.update(),
        )

    if record.get("password_hash") != hash_pw(password):
        return (
            "Incorrect password.",
            user_state,
            user_info_state,
            gr.update(),
            gr.update(),
            gr.update(),
        )

    new_user_state = {"logged_in": True, "username": username}
    info = load_user_info_dict(username)
    new_user_info_state = info

    msg = f"Login successful, welcome {info.get('first_name') or username}!"

    return (
        msg,
        new_user_state,
        new_user_info_state,
        gr.update(visible=False),   # hide login panel
        gr.update(visible=False),   # hide register panel
        gr.update(visible=True),    # show main panel
    )


def show_register_panel():
    return gr.update(visible=False), gr.update(visible=True)


def back_to_login_panel():
    return gr.update(visible=True), gr.update(visible=False)


def register_action(
    reg_username,
    reg_password,
    reg_password2,
    first_name,
    last_name,
    gender,
    occupation,
    phone,
    email,
    height,
    initial_weight,
    body_measurements,
    weight_statement,
    allergy,
    medication,
    lifestyle,
    medical_history,
    user_state,
    user_info_state,
):
    ensure_base_dir()
    db = load_users_db()

    if not reg_username or not reg_password:
        return (
            "Username and password are required.",
            user_state,
            user_info_state,
            gr.update(),
            gr.update(),
            gr.update(),
        )

    if reg_password != reg_password2:
        return (
            "Passwords do not match.",
            user_state,
            user_info_state,
            gr.update(),
            gr.update(),
            gr.update(),
        )

    if reg_username in db:
        return (
            "This username already exists. Please choose another one.",
            user_state,
            user_info_state,
            gr.update(),
            gr.update(),
            gr.update(),
        )

    user_dir = get_user_dir(reg_username)
    os.makedirs(user_dir, exist_ok=True)

    info = default_user_info()
    info.update(
        {
            "first_name": first_name or "",
            "last_name": last_name or "",
            "gender": gender or "",
            "occupation": occupation or "",
            "phone": phone or "",
            "email": email or "",
            "height": height or "",
            "initial_weight": initial_weight or "",
            "body_measurements": body_measurements or "",
            "weight_statement": weight_statement or "",
            "allergy": allergy or "N/A",
            "medication": medication or "N/A",
            "lifestyle": lifestyle or "N/A",
            "medical_history": medical_history or "N/A",
            "photo_path": None,
            "register_date": today_str(),
        }
    )
    save_user_info_dict(reg_username, info)

    # initialize user-related JSON files
    save_progress_data(reg_username, {})
    save_goals_data(reg_username, {})
    save_chats_index(reg_username, {"conversations": []})

    db[reg_username] = {
        "password_hash": hash_pw(reg_password),
        "first_name": first_name,
        "last_name": last_name,
        "folder": user_dir,
    }
    save_users_db(db)

    new_user_state = {"logged_in": True, "username": reg_username}
    new_user_info_state = info

    msg = f"Registration successful. Welcome, {first_name}! Your personal data folder has been created."

    return (
        msg,
        new_user_state,
        new_user_info_state,
        gr.update(visible=False),  # hide login panel
        gr.update(visible=False),  # hide register panel
        gr.update(visible=True),   # show main panel
    )


def logout_action(user_state, user_info_state, chat_history_state, chat_meta_state):
    new_user_state = {"logged_in": False, "username": None}
    new_user_info_state = {}
    new_chat_history = []
    new_chat_meta = {"active": False, "date": None, "index": None, "finished": True, "username": None}

    return (
        new_user_state,
        new_user_info_state,
        new_chat_history,
        new_chat_meta,
        gr.update(visible=True),   # login_panel
        gr.update(visible=False),  # register_panel
        gr.update(visible=False),  # main_panel
    )


# ================== Profile load / save / edit ==================


def load_profile_action(user_state, user_info_state):
    if not user_state.get("logged_in"):
        return (
            "", "", "", "", "", "", "", "", "", "",
            "", "", "", "", None, "", "Please log in first."
        )

    username = user_state.get("username")
    info = load_user_info_dict(username)

    return (
        info.get("first_name", ""),
        info.get("last_name", ""),
        info.get("gender", ""),
        info.get("occupation", ""),
        info.get("phone", ""),
        info.get("email", ""),
        info.get("height", ""),
        info.get("initial_weight", ""),
        info.get("body_measurements", ""),
        info.get("weight_statement", ""),
        info.get("allergy", ""),
        info.get("medication", ""),
        info.get("lifestyle", ""),
        info.get("medical_history", ""),
        info.get("photo_path", None),
        info.get("register_date", ""),
        "User information loaded from local storage.",
    )


def save_profile_action(
    first_name,
    last_name,
    gender,
    occupation,
    phone,
    email,
    height,
    initial_weight,
    body_measurements,
    weight_statement,
    allergy,
    medication,
    lifestyle,
    medical_history,
    photo_file,
    user_state,
    user_info_state,
):
    if not user_state.get("logged_in"):
        return "Please log in first."

    username = user_state.get("username")
    info = load_user_info_dict(username)

    info.update(
        {
            "first_name": first_name or "",
            "last_name": last_name or "",
            "gender": gender or "",
            "occupation": occupation or "",
            "phone": phone or "",
            "email": email or "",
            "height": height or "",
            "initial_weight": initial_weight or "",
            "body_measurements": body_measurements or "",
            "weight_statement": weight_statement or "",
            "allergy": allergy or "N/A",
            "medication": medication or "N/A",
            "lifestyle": lifestyle or "N/A",
            "medical_history": medical_history or "N/A",
        }
    )

    if photo_file is not None:
        user_dir = get_user_dir(username)
        photo_path = os.path.join(user_dir, "photo.png")
        with open(photo_file, "rb") as src, open(photo_path, "wb") as dst:
            dst.write(src.read())
        info["photo_path"] = photo_path

    save_user_info_dict(username, info)

    return "User information has been saved locally."


def profile_edit_toggle(
    profile_edit_state,
    first_name,
    last_name,
    gender,
    occupation,
    phone,
    email,
    height,
    initial_weight,
    body_measurements,
    weight_statement,
    allergy,
    medication,
    lifestyle,
    medical_history,
    photo_upload,
    user_state,
    user_info_state,
):
    if not user_state.get("logged_in"):
        return (
            profile_edit_state,
            "Please log in first.",
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(), gr.update(), gr.update(), gr.update(),
            gr.update(), gr.update(), gr.update(),
        )

    if not profile_edit_state:
        msg = "You can now edit your personal information."
        new_state = True
        inter = gr.update(interactive=True)
        return (
            new_state,
            msg,
            inter, inter, inter, inter,
            inter, inter, inter, inter,
            inter, inter, inter, inter,
            gr.update(interactive=False),  # register_date stays read-only
            gr.update(interactive=True),   # photo upload enabled
            gr.update(value="Save personal information"),
        )

    msg = save_profile_action(
        first_name,
        last_name,
        gender,
        occupation,
        phone,
        email,
        height,
        initial_weight,
        body_measurements,
        weight_statement,
        allergy,
        medication,
        lifestyle,
        medical_history,
        photo_upload,
        user_state,
        user_info_state,
    )
    new_state = False
    inter_false = gr.update(interactive=False)
    return (
        new_state,
        msg,
        inter_false, inter_false, inter_false, inter_false,
        inter_false, inter_false, inter_false, inter_false,
        inter_false, inter_false, inter_false, inter_false,
        gr.update(interactive=False),
        gr.update(interactive=False),
        gr.update(value="Edit personal information"),
    )
