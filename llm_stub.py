# llm_stub.py
"""

logic_chat.py currently calls:
    llm_reply_stub(user_input, user_state, user_info_state, goals_feedback)

"""

from __future__ import annotations

from agents.chat import chat_agent

def llm_reply_stub(
    user_input: str,
    user_state,
    user_info_state,
    goals_feedback: str,
    prompt_patch: str | None = None,
    base_prompt: str | None = None,
) -> str:
    """
    Backward-compatible wrapper used by logic_chat.py.

    In UI_TEST_MODE, ChatAgent will return a dummy reply.
    Otherwise, it will call a real LLM backend via an OpenAI-style API.
    """
    return chat_agent.reply(
        user_input,
        user_state,
        user_info_state,
        goals_feedback,
        prompt_patch=prompt_patch,
        base_prompt=base_prompt,
    )
