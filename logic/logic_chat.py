import os
from datetime import datetime
from typing import Dict, Any, List, Tuple

import gradio as gr

from storage import get_user_dir, get_user_file, load_json, save_json, today_str
from .logic_goals import load_goals_data, save_extractor_summary
from llm_stub import llm_reply_stub

from agents.chat import chat_agent  
from agents.extractor import extractor_agent
from agents.generator import (
    apply_delta_text,
    build_initial_cst,
    ensure_fixed_state_shape,
    generate_prompt_patch,
    state_to_text,
)
from agents.prompt_chat import (
    COACH_SYSTEM_PROMPT_1ST_SESSION,
    COACH_SYSTEM_PROMPT_IDENTITY,
    COACH_SYSTEM_PROMPT_IDENTITY2
)
from .logic_progress import load_progress_data


def get_chats_dir(username: str) -> str:
    directory = os.path.join(get_user_dir(username), "chats")
    os.makedirs(directory, exist_ok=True)
    return directory


def get_chats_index_path(username: str) -> str:
    return os.path.join(get_chats_dir(username), "chats_index.json")


def get_cst_dir(username: str) -> str:
    directory = os.path.join(get_user_dir(username), "coach_state_tracker")
    os.makedirs(directory, exist_ok=True)
    return directory


def get_cst_filename(date_str: str, index: int) -> str:
    return f"{date_str}_cst{index}.json"


def load_cst(username: str, date_str: str, index: int) -> Dict[str, Any]:
    path = os.path.join(get_cst_dir(username), get_cst_filename(date_str, index))
    return load_json(path, {})


def save_cst(username: str, date_str: str, index: int, cst: Dict[str, Any]) -> None:
    path = os.path.join(get_cst_dir(username), get_cst_filename(date_str, index))
    save_json(path, cst)


def get_session_reports_dir(username: str) -> str:
    directory = os.path.join(get_user_dir(username), "session_report")
    os.makedirs(directory, exist_ok=True)
    return directory


def get_session_report_filename(date_str: str, index: int) -> str:
    return f"{date_str}_session_report{index}.json"


def save_session_report(
    username: str,
    meta: Dict[str, Any],
    summary_text: str,
) -> None:
    if not meta.get("date") or not meta.get("index"):
        return
    data = {
        "date": meta["date"],
        "index": meta["index"],
        "summary": summary_text,
    }
    path = os.path.join(
        get_session_reports_dir(username),
        get_session_report_filename(meta["date"], meta["index"]),
    )
    save_json(path, data)


def _get_mode() -> int:
    try:
        return int(os.getenv("SYSTEM_MODE", "0"))
    except Exception:
        return 0


def _build_history_text(
    chat_history_state: List[Tuple[str, str]],
    last_n: int | None = None,
) -> str:
    lines: List[str] = []
    turns = chat_history_state if last_n is None else chat_history_state[-last_n:]
    for user_text, assistant_text in turns:
        lines.append(f"User: {str(user_text).strip()}")
        lines.append(f"Agent: {str(assistant_text).strip()}")
    return "\n".join(lines).strip()


def _parse_session_key(filename: str) -> Tuple[datetime, int]:
    if not filename.endswith(".json"):
        return datetime.min, 0
    base = filename[:-5]
    if "_session_report" in base:
        date_part, _, idx_part = base.partition("_session_report")
    elif "_cst" in base:
        date_part, _, idx_part = base.partition("_cst")
    else:
        return datetime.min, 0
    try:
        date_val = datetime.strptime(date_part, "%Y-%m-%d")
    except Exception:
        return datetime.min, 0
    try:
        idx_val = int(idx_part)
    except Exception:
        idx_val = 0
    return date_val, idx_val


def load_latest_session_report(username: str) -> str:
    report_dir = get_session_reports_dir(username)
    try:
        files = [f for f in os.listdir(report_dir) if f.endswith(".json")]
    except Exception:
        return ""
    if not files:
        return ""
    files.sort(key=lambda f: _parse_session_key(f))
    latest_path = os.path.join(report_dir, files[-1])
    data = load_json(latest_path, {})
    return data.get("summary", "") or ""


def load_all_session_reports(username: str) -> str:
    report_dir = get_session_reports_dir(username)
    try:
        files = [f for f in os.listdir(report_dir) if f.endswith(".json")]
    except Exception:
        return ""
    if not files:
        return ""
    files.sort(key=lambda f: _parse_session_key(f))
    lines: List[str] = []
    for filename in files:
        date_val, idx_val = _parse_session_key(filename)
        data = load_json(os.path.join(report_dir, filename), {})
        summary = data.get("summary", "") or ""
        if summary:
            lines.append(f"Session {idx_val} ({date_val.date()}): {summary}")
    return "\n".join(lines).strip()


def load_latest_cst(username: str) -> Dict[str, Any]:
    cst_dir = get_cst_dir(username)
    try:
        files = [f for f in os.listdir(cst_dir) if f.endswith(".json")]
    except Exception:
        return {}
    if not files:
        return {}
    files.sort(key=lambda f: _parse_session_key(f))
    latest_path = os.path.join(cst_dir, files[-1])
    return load_json(latest_path, {})


def _is_first_turn_first_session(
    username: str,
    date_str: str | None,
    session_idx: int | None,
    chat_history_state: List[Tuple[str, str]],
) -> bool:
    if not date_str or not session_idx:
        return False
    if chat_history_state:
        return False
    if session_idx != 1:
        return False
    index = load_chats_index(username)
    convs = index.get("conversations", [])
    for conv in convs:
        if conv.get("date") != date_str or conv.get("index") != session_idx:
            return False
    return True


def load_chats_index(username: str) -> Dict[str, Any]:
    path = get_chats_index_path(username)
    return load_json(path, {"conversations": []})


def save_chats_index(username: str, index: Dict[str, Any]) -> None:
    path = get_chats_index_path(username)
    save_json(path, index)


def get_conversation_filename(date_str: str, index: int) -> str:
    return f"{date_str}_chat{index}.json"


def load_conversation(username: str, date_str: str, idx: int):
    path = os.path.join(
        get_chats_dir(username),
        get_conversation_filename(date_str, idx),
    )
    data = load_json(path, {})
    msgs = data.get("messages", [])
    history: List[Tuple[str, str]] = []
    for item in msgs:
        u = item.get("user", "")
        a = item.get("assistant", "")
        history.append((u, a))
    finished = data.get("finished", False)
    return history, finished


def save_conversation(
    username: str,
    meta: Dict[str, Any],
    history: List[Tuple[str, str]],
) -> None:
    if not meta.get("date") or not meta.get("index"):
        return
    msgs = [{"user": u, "assistant": a} for (u, a) in history]
    data = {
        "date": meta["date"],
        "index": meta["index"],
        "finished": meta.get("finished", False),
        "messages": msgs,
    }
    path = os.path.join(
        get_chats_dir(username),
        get_conversation_filename(meta["date"], meta["index"]),
    )
    save_json(path, data)


def start_new_chat_action(user_state, chat_history_state, chat_meta_state):
    if not user_state.get("logged_in"):
        return (
            chat_history_state,
            chat_meta_state,
            "Please log in first.",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    username = user_state.get("username")
    today = today_str()
    index = load_chats_index(username)
    convs = index.get("conversations", [])

    todays = [c for c in convs if c.get("date") == today]
    if todays:
        new_idx = max(c.get("index", 0) for c in todays) + 1
    else:
        new_idx = 1

    meta = {
        "username": username,
        "date": today,
        "index": new_idx,
        "finished": False,
        "active": True,
    }

    convs.append(
        {
            "date": today,
            "index": new_idx,
            "file": get_conversation_filename(today, new_idx),
            "finished": False,
        }
    )
    index["conversations"] = convs
    save_chats_index(username, index)

    new_history: List[Tuple[str, str]] = []
    save_conversation(username, meta, new_history)

    session_timestamp = f"{today}_session{new_idx}"
    cst_state = load_latest_cst(username)
    if cst_state:
        cst_state = ensure_fixed_state_shape(cst_state)
        cst_state["session"]["session_timestamp"] = session_timestamp
        cst_state = apply_delta_text(cst_state, None, session_num=new_idx)
    else:
        cst_state = build_initial_cst(session_timestamp, session_num=new_idx)
    save_cst(username, today, new_idx, cst_state)

    msg = f"Started a new conversation: {today}, session {new_idx}."

    return (
        new_history,
        meta,
        msg,
        gr.update(value=new_history, visible=True),  # chatbot
        gr.update(value="", visible=True),           # chat_input
        gr.update(visible=True),                     # send button
        gr.update(visible=True),                     # end button
    )


def continue_chat_action(user_state, chat_history_state, chat_meta_state):
    if not user_state.get("logged_in"):
        return (
            chat_history_state,
            chat_meta_state,
            "Please log in first.",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    username = user_state.get("username")
    index = load_chats_index(username)
    convs = index.get("conversations", [])

    unfinished = [c for c in convs if not c.get("finished", False)]
    if not unfinished:
        return (
            chat_history_state,
            chat_meta_state,
            "There is no unfinished conversation.",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    conv = sorted(unfinished, key=lambda c: (c.get("date"), c.get("index")))[-1]
    date_str = conv["date"]
    idx = conv["index"]

    history, finished = load_conversation(username, date_str, idx)

    meta = {
        "username": username,
        "date": date_str,
        "index": idx,
        "finished": finished,
        "active": not finished,
    }

    msg = f"Loaded unfinished conversation: {date_str}, session {idx}."
    show_input = not finished

    if finished:
        msg += (
            " (This conversation is marked as finished "
            "and will be shown as read-only.)"
        )

    return (
        history,
        meta,
        msg,
        gr.update(value=history, visible=True),
        gr.update(value="", visible=show_input),
        gr.update(visible=show_input),
        gr.update(visible=show_input),
    )


def end_chat_action(user_state, chat_history_state, chat_meta_state):
    if not user_state.get("logged_in"):
        return (
            chat_meta_state,
            "Please log in first.",
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    if not chat_meta_state.get("active"):
        return (
            chat_meta_state,
            "There is no active conversation.",
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    username = user_state.get("username")
    date_str = chat_meta_state.get("date")
    idx = chat_meta_state.get("index")
    if not date_str or not idx:
        return (
            chat_meta_state,
            "Conversation metadata is incomplete.",
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
        )

    new_meta = dict(chat_meta_state)
    new_meta["finished"] = True
    new_meta["active"] = False

    index = load_chats_index(username)
    convs = index.get("conversations", [])
    for c in convs:
        if c.get("date") == date_str and c.get("index") == idx:
            c["finished"] = True
    index["conversations"] = convs
    save_chats_index(username, index)

    save_conversation(username, new_meta, chat_history_state)

    mode = _get_mode()
    if mode in {0, 1}:
        try:
            report_text = extractor_agent.gen_session_report(chat_history_state)
            save_session_report(username, new_meta, report_text)
        except Exception as e:
            msg = (
                f"Conversation ended: {date_str}, session {idx}. "
                f"Session report generation failed: {e}"
            )
        else:
            msg = (
                f"Conversation ended: {date_str}, session {idx}. "
                "Next new conversation will use session index +1."
            )
    else:
        msg = (
            f"Conversation ended: {date_str}, session {idx}. "
            "Next new conversation will use session index +1."
        )

    return (
        new_meta,
        msg,
        gr.update(visible=False),  # chatbot
        gr.update(visible=False),  # chat_input
        gr.update(visible=False),  # send button
        gr.update(visible=False),  # end button
    )


def chat_send_action(
    user_input: str,
    chat_history_state,
    user_state,
    user_info_state,
    chat_meta_state,
):
    """
    Handle one user message in the current conversation.

    - Call the main chat LLM (llm_reply_stub).
    - Update the per-conversation JSON file.
    - Call the extractor agent to update today's goal summary in goals.json.
    """
    if not user_state.get("logged_in"):
        return chat_history_state, "Please log in first.", chat_history_state, ""

    if not user_input:
        return chat_history_state, "", chat_history_state, ""

    if not chat_meta_state.get("active"):
        return (
            chat_history_state,
            "Click 'Start new conversation' or 'Continue unfinished conversation' first.",
            chat_history_state,
            "",
        )

    username = user_state.get("username") or "user"

    # 1) Get today's goal feedback (if any) and pass it to the chat LLM
    goals_data = load_goals_data(username)
    today = today_str()
    goals_entry = goals_data.get(today, {})
    summary_text = goals_entry.get("summary", "") or ""
    feedback_text = goals_entry.get("feedback", "") or ""
    
    progress_data = load_progress_data(username)
    progress_entry = {}
    if today in progress_data:
        progress_entry = progress_data[today]
     
    goals_context_parts: List[str] = []
    # goals_context_parts.append(f"- Session: {session_idx}")

    if progress_entry:
        lines = ["Latest daily progress logged by the user for this plan day:"]
        for k, v in progress_entry.items():
            if v not in ("", None):
                lines.append(f"- {k}: {v}")
        goals_context_parts.append("\n".join(lines))


    if summary_text:
        goals_context_parts.append(
            "Latest structured goal summary for this user:\n" + summary_text
        )
    if feedback_text:
        goals_context_parts.append(
            "User's latest goal feedback on these goals:\n" + feedback_text
        )
    goals_context = "\n\n".join(goals_context_parts)
    
    # goals_context = "\n"

    mode = _get_mode()
    previous_agent = None
    if chat_history_state:
        _, last_assistant = chat_history_state[-1]
        previous_agent = last_assistant

    extractor_output = ""
    status_msg = ""
    if mode == 0:
        try:
            extractor_output = extractor_agent.extract_summary_json(previous_agent, user_input)
        except Exception as e:
            status_msg = (
                "Message sent, but extractor failed to update goals: "
                f"{e}"
            )

    date_str = chat_meta_state.get("date")
    session_idx = chat_meta_state.get("index")
    prompt_patch = ""
    first_turn = not chat_history_state
    if mode == 0:
        base_prompt = COACH_SYSTEM_PROMPT_IDENTITY2
    elif mode in {1, 2}:
        base_prompt = COACH_SYSTEM_PROMPT_IDENTITY
    else:
        base_prompt = COACH_SYSTEM_PROMPT_IDENTITY
    include_fewshot = mode != 3
    cst_text = ""
    new_session_start = first_turn
    meta_text = f"Meta: user={username}, session={session_idx}"
    if new_session_start:
        meta_text += ", new_session_start=true, generator_priority=review_progress"
    if date_str and session_idx and mode == 0:
        try:
            cst_state = load_cst(username, date_str, session_idx)
            if not cst_state:
                cst_state = load_latest_cst(username)
                session_timestamp = f"{date_str}_session{session_idx}"
                if cst_state:
                    cst_state = ensure_fixed_state_shape(cst_state)
                    cst_state["session"]["session_timestamp"] = session_timestamp
                else:
                    cst_state = build_initial_cst(session_timestamp, session_num=session_idx)
            cst_state["session"]["session_timestamp"] = f"{date_str}_session{session_idx}"
            cst_state = apply_delta_text(
                cst_state,
                extractor_output if extractor_output else None,
                session_num=session_idx,
            )
            history_for_patch = _build_history_text(chat_history_state, last_n=5)
            prompt_patch = generate_prompt_patch(
                cst_state,
                chat_history_text=history_for_patch,
                meta_text=meta_text,
            )
            save_cst(username, date_str, session_idx, cst_state)
            cst_text = state_to_text(cst_state)
        except Exception as e:
            if not status_msg:
                status_msg = f"Message sent, but CST update failed: {e}"

    first_session_first_turn = _is_first_turn_first_session(
        username,
        date_str,
        session_idx,
        chat_history_state,
    )
    if first_session_first_turn:
        base_prompt = COACH_SYSTEM_PROMPT_1ST_SESSION
        prompt_patch = ""
    elif mode == 1:
        if first_turn:
            prompt_patch = load_latest_session_report(username)
        else:
            prompt_patch = ""
    elif mode == 0:
        if first_turn:
            prompt_patch = load_latest_session_report(username)
    else:
        prompt_patch = ""

    latest_report = ""
    if mode in {0, 1}:
        latest_report = load_latest_session_report(username)
    if new_session_start and latest_report and not first_session_first_turn:
        base_prompt = (
            (base_prompt or "") + "IMPORTANT: New session start: summarize last session based on the report first and then ask the current progress.\n\n"
        )
    base_prompt = meta_text + "\n\n" + (base_prompt or "")
    if mode == 3:
        base_prompt = meta_text

    memory_text = ""
    if mode in {0, 1} and latest_report:
        memory_text = "Last session report:\n" + latest_report
    if mode == 0 and cst_text:
        cst_block = "Current CST:\n" + cst_text
        if memory_text:
            memory_text = memory_text + "\n\n" + cst_block
        else:
            memory_text = cst_block

    recent_history_text = ""
    user_input_text = user_input
    if mode == 0:
        recent_history_text = _build_history_text(chat_history_state, last_n=5)
        if recent_history_text:
            recent_history_text = "Recent chat history:\n" + recent_history_text
    elif mode == 1:
        recent_history_text = _build_history_text(chat_history_state, last_n=5)
        if recent_history_text:
            recent_history_text = "Recent chat history:\n" + recent_history_text
    elif mode in {2, 3}:
        history_text = _build_history_text(chat_history_state, last_n=5)
        if history_text:
            recent_history_text = history_text + "\nUser: " + user_input
        else:
            recent_history_text = "User: " + user_input
        user_input_text = ""

    system_prompt = chat_agent.build_system_prompt_for_ui(
        user_state,
        user_info_state,
        goals_context,
        prompt_patch=prompt_patch,
        base_prompt=base_prompt,
        include_fewshot=include_fewshot,
    )

    debug_messages = chat_agent.build_messages(
        user_input_text,
        user_state,
        user_info_state,
        goals_context,
        prompt_patch=prompt_patch,
        base_prompt=base_prompt,
        memory_text=memory_text,
        recent_history_text=recent_history_text,
        include_fewshot=include_fewshot,
    )
    debug_message_text = "\n\n".join(
        f"{m['role']}:\n{m['content']}" for m in debug_messages
    ).strip()

    reply = llm_reply_stub(
        user_input_text,
        user_state,
        user_info_state,
        goals_context,
        prompt_patch=prompt_patch,
        base_prompt=base_prompt,
        memory_text=memory_text,
        recent_history_text=recent_history_text,
        include_fewshot=include_fewshot,
    )

    # 2) Update in-memory chat history and save this conversation
    new_history = chat_history_state + [(user_input, reply)]

    meta = dict(chat_meta_state)
    meta["username"] = username
    save_conversation(username, meta, new_history)

    # 4) Call the extractor and store today's summary in goals.json
    try:
        if extractor_output:
            save_extractor_summary(username, today, extractor_output)
    except Exception as e:
        # Do not break the chat if extractor fails; just surface a status message.
        status_msg = (
            "Message sent, but extractor failed to update goals: "
            f"{e}"
        )

    # Chatbot UI uses tuples, so we return new_history for both internal state and display.
    return new_history, status_msg, new_history, system_prompt, debug_message_text, cst_text


def refresh_history_list_action(user_state):
    from storage import load_json  # already imported above, but keep explicit for clarity

    if not user_state.get("logged_in"):
        return gr.update(choices=[], value=None), "Please log in first."

    username = user_state.get("username")
    index = load_chats_index(username)
    convs = index.get("conversations", [])
    if not convs:
        return (
            gr.update(choices=[], value=None),
            "No conversations have been recorded yet.",
        )

    sorted_convs = sorted(convs, key=lambda x: (x.get("date"), x.get("index")))
    choices = [f"{c['date']}|{c['index']}" for c in sorted_convs]

    return (
        gr.update(choices=choices, value=None),
        f"{len(convs)} conversations found. Please select one from the dropdown.",
    )


def load_history_conversation_action(user_state, selection: str):
    if not user_state.get("logged_in"):
        return [], "Please log in first."

    if not selection:
        return [], "Please choose a conversation from the dropdown."

    username = user_state.get("username")
    try:
        date_str, idx_str = selection.split("|")
        idx = int(idx_str)
    except Exception:
        return [], "Failed to parse the selected conversation ID."

    history, finished = load_conversation(username, date_str, idx)
    status = "finished" if finished else "active"
    msg = f"Showing conversation: {date_str}, session {idx} ({status})."
    return history, msg
