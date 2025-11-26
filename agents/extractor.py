from typing import Dict, List

from agents.base import OpenAIStyleClient

from llm_config import (
    UI_TEST_MODE,
    VLLM_BASE_URL,
    EXTRACTOR_MODEL_NAME,
)

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
        self.client = OpenAIStyleClient(VLLM_BASE_URL, EXTRACTOR_MODEL_NAME)

    def build_messages(self, text_block: str) -> List[Dict[str, str]]:
        system_prompt = (
            "You are a summarizer and information extractor for a health-coaching dialog. "
            "Given the recent conversation text, identify:\n"
            "- the user's current goals,\n"
            "- main obstacles or difficulties,\n"
            "- any concrete actions or progress mentioned.\n\n"
            "Return your answer as a compact JSON object with the keys:\n"
            "{\n"
            '  "goals": [list of short goal strings],\n'
            '  "obstacles": [list of short obstacle strings],\n'
            '  "progress": [list of short progress/action strings],\n'
            '  "other_notes": [list of any other important details]\n'
            "}\n\n"
            "Do not include any additional text outside the JSON. "
            "If you cannot infer something, use an empty list for that field."
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "Here is the recent conversation text:\n\n" + text_block.strip(),
            },
        ]
        return messages

    def extract_summary_json(self, text_block: str) -> str:
        """
        Return a JSON string with the structure described in build_messages().
        The caller is responsible for parsing & storing it (e.g., in a JSON file).
        """
        if UI_TEST_MODE:
            # In UI test mode we return an empty but valid JSON skeleton.
            return (
                '{\n'
                '  "goals": [],\n'
                '  "obstacles": [],\n'
                '  "progress": [],\n'
                '  "other_notes": []\n'
                "}"
            )

        messages = self.build_messages(text_block)
        try:
            return self.client.chat(messages, temperature=0.2, max_tokens=256)
        except Exception as e:
            # Return a JSON-looking error to avoid crashing JSON parsers too badly
            return (
                '{\n'
                f'  "error": "Extractor agent failed: {str(e)}"\n'
                "}"
            )


extractor_agent = ExtractorAgent()