import os
from typing import Dict, Any, List, Tuple

import gradio as gr

from storage import get_user_dir, get_user_file, load_json, save_json, today_str
from .logic_goals import load_goals_data, save_extractor_summary
from llm_stub import llm_reply_stub
from agents.extractor import extractor_agent


def get_chats_dir(username: str) -> str:
    directory = os.path.join(get_user_dir(username), "chats")
    os.makedirs(directory, exist_ok=True)
    return directory


def get_chats_index_path(username: str) -> str:
    return os.path.join(get_chats_dir(username), "chats_index.json")


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
        return chat_history_state, "Please log in first.", chat_history_state

    if not user_input:
        return chat_history_state, "", chat_history_state

    if not chat_meta_state.get("active"):
        return (
            chat_history_state,
            "Click 'Start new conversation' or 'Continue unfinished conversation' first.",
            chat_history_state,
        )

    username = user_state.get("username") or "user"

    # 1) Get today's goal feedback (if any) and pass it to the chat LLM
    goals_data = load_goals_data(username)
    today = today_str()
    goals_entry = goals_data.get(today, {})
    feedback = goals_entry.get("feedback", "")

    reply = llm_reply_stub(user_input, user_state, user_info_state, feedback)

    # 2) Update in-memory chat history and save this conversation
    new_history = chat_history_state + [(user_input, reply)]

    meta = dict(chat_meta_state)
    meta["username"] = username
    save_conversation(username, meta, new_history)

    # 3) Build a snippet for the extractor agent (Agent B)
    prev_q = None
    if chat_history_state:
        # Take the last assistant message as the previous coach question/statement
        _last_user, last_assistant = chat_history_state[-1]
        prev_q = last_assistant

    kb_input_lines: List[str] = []
    if prev_q:
        kb_input_lines.append(f"Coach_previous_question: {prev_q}")
    kb_input_lines.append(f"User_answer: {user_input}")
    kb_input_lines.append(f"Coach_current_reply: {reply}")
    kb_input_text = "\n".join(kb_input_lines)

    # 4) Call the extractor and store today's summary in goals.json
    status_msg = ""
    try:
        summary_json_str = extractor_agent.extract_summary_json(kb_input_text)
        save_extractor_summary(username, today, summary_json_str)
    except Exception as e:
        # Do not break the chat if extractor fails; just surface a status message.
        status_msg = (
            "Message sent, but extractor failed to update goals: "
            f"{e}"
        )

    # Chatbot UI uses tuples, so we return new_history for both internal state and display.
    return new_history, status_msg, new_history


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
