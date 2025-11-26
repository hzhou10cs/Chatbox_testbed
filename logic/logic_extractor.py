# logic_extractor.py
"""
Glue code between ExtractorAgent (Agent B) and the on-disk STATE_JSON.
"""

from typing import Dict, List, Tuple

from agents.extractor import extractor_agent
from coach_state_io import load_state, atomic_write_json


def update_state_file_from_turn(
    state_json_path: str,
    prev_question: str | None,
    user_text: str,
    coach_reply: str,
) -> Tuple[Dict, List[Tuple[List[str], str]]]:
    """
    Load STATE_JSON, run extractor, apply deltas, and write state back.

    Returns:
    - new_state dict
    - deltas list (path, value)
    """
    state = load_state(state_json_path)
    new_state, deltas = extractor_agent.update_state_from_turn(
        prev_question=prev_question,
        user_text=user_text,
        coach_reply=coach_reply,
        state=state,
    )
    atomic_write_json(state_json_path, new_state)
    return new_state, deltas
