# llm_api.py
"""
Compatibility wrapper for older code.

logic_chat.py currently calls:
    llm_reply_stub(user_input, user_state, user_info_state, goals_feedback)

We keep that function here, but internally delegate to ChatAgent from llm_agents.py.
"""

from __future__ import annotations

from agents.chat import chat_agent


def llm_reply_stub(
    user_input: str,
    user_state,
    user_info_state,
    goals_feedback: str,
) -> str:
    """
    Backward-compatible wrapper used by logic_chat.py.

    In UI_TEST_MODE, ChatAgent will return a dummy reply.
    Otherwise, it will call a real LLM backend via an OpenAI-style API.
    """
    return chat_agent.reply(user_input, user_state, user_info_state, goals_feedback)

