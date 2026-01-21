from typing import Dict, List, Optional

from agents.base import OpenAIStyleClient
from agents.prompt_helper import EXAMPLES_B, PROMPT_EXTRACT, SESSION_SUMMARY

from llm_config import (
    UI_TEST_MODE,
    LLM_BASE_URL,
    EXTRACTOR_MODEL_NAME,
)


def _format_extractor_input(agent_text: Optional[str], user_text: str) -> str:
    agent_part = agent_text.strip() if agent_text else "NULL"
    user_part = user_text.strip()
    return f"Agent: {agent_part}\nUser: {user_part}"


def build_extraction_messages(
    agent_text: Optional[str],
    user_text: str,
    include_examples: bool = True,
) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": PROMPT_EXTRACT.strip()}
    ]
    if include_examples:
        for user_example, assistant_example in EXAMPLES_B:
            messages.append({"role": "user", "content": user_example})
            messages.append({"role": "assistant", "content": assistant_example})
    messages.append({"role": "user", "content": _format_extractor_input(agent_text, user_text)})
    return messages


class ExtractorAgent:
    """
    Extractor / summarizer agent.

    This agent is meant to:
    - read a block of recent conversation text (e.g., question + answer + reply)
    - output a concise JSON-like summary of goals, obstacles, and progress.

    For now, we implement a simple JSON summary prompt. Later you can replace this
    with your more advanced dual-agent <STATE> schema.
    """

    def __init__(self):
        self.client = OpenAIStyleClient(LLM_BASE_URL, EXTRACTOR_MODEL_NAME)

    def build_messages(self, agent_text: Optional[str], user_text: str) -> List[Dict[str, str]]:
        return build_extraction_messages(agent_text, user_text, include_examples=True)

    def extract_summary_json(self, agent_text: Optional[str], user_text: str) -> str:
        """
        Return a delta text block following PROMPT_EXTRACT instructions.
        The caller is responsible for parsing & storing it (e.g., in a JSON file).
        """
        if UI_TEST_MODE:
            return "NONE"

        messages = self.build_messages(agent_text, user_text)
        try:
            return self.client.chat(messages, temperature=0.2, max_tokens=256)
        except Exception as e:
            return f"[Extractor error] {e}"

    def gen_session_report(self, chat_history: List[Dict[str, str]] | List[tuple]) -> str:
        """
        Summarize the current session using SESSION_SUMMARY prompt.
        """
        if UI_TEST_MODE:
            return ""

        lines: List[str] = []
        for item in chat_history or []:
            if isinstance(item, dict):
                user_text = item.get("user", "")
                assistant_text = item.get("assistant", "")
            else:
                user_text, assistant_text = item
            lines.append(f"User: {str(user_text).strip()}")
            lines.append(f"Agent: {str(assistant_text).strip()}")

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": SESSION_SUMMARY},
            {
                "role": "user",
                "content": (
                    "Generate a Session Stage Report that will seed the next coaching session.\n"
                    + "\n".join(lines).strip()
                ),
            },
        ]
        return self.client.chat(messages, temperature=0.2, max_tokens=512)


extractor_agent = ExtractorAgent()
