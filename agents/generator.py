import json
import re
from typing import Dict, List, Optional, Tuple, Union

from agents.base import OpenAIStyleClient
from agents.prompt_generator import GENERATOR_PROMPT_V1
from llm_config import CHAT_MODEL_NAME, LLM_BASE_URL, UI_TEST_MODE


class GeneratorAgent:
    """
    Generator agent that reuses the same API client.
    """

    def __init__(self):
        self.client = OpenAIStyleClient(LLM_BASE_URL, CHAT_MODEL_NAME)

    def generate(self, messages: List[Dict[str, str]]) -> str:
        if UI_TEST_MODE:
            return ""
        return self.client.chat(messages)


generator_agent = GeneratorAgent()

# ---------------- Fixed schema ----------------

ALLOWED_DOMAINS = {"activity", "nutrition", "sleep"}
ALLOWED_GOAL_KEYS = {"Specific", "Measurable", "Attainable", "Reward", "Timeframe"}
ALLOWED_LEAVES = {
    "session": {"session_timestamp", "agenda"},
    "activity": {"existing_plan", "progress", "barrier", "goal_set"},
    "nutrition": {"existing_plan", "progress", "barrier", "goal_set"},
    "sleep": {"existing_plan", "progress", "barrier", "goal_set"},
}


def _is_none_like(s: Optional[str]) -> bool:
    if s is None:
        return True
    if not isinstance(s, str):
        s = str(s)
    return s.strip() == "" or s.strip().lower() in {"none", "null", "n/a"}


def _append_text(
    existing: Optional[str],
    new: str,
    sep: str = "; ",
    max_len: Optional[int] = None,
) -> str:
    """
    Append `new` to `existing` with a separator.
    - If existing is None/empty/"None", return new.
    - Avoid duplicates (case-insensitive exact match of segment).
    - Optionally cap length.
    """
    new = (new or "").strip()
    if not new:
        return existing or ""
    if _is_none_like(existing):
        result = new
    else:
        ex = str(existing).strip()
        tokens = [t.strip().lower() for t in re.split(r"[;|,/]\s*", ex) if t.strip()]
        if new.lower() in tokens:
            result = ex
        else:
            if ex.endswith(tuple([";", "|", ",", "/"])):
                result = ex + " " + new
            else:
                result = ex + sep + new

    if max_len is not None and len(result) > max_len:
        result = result[:max_len].rstrip()
    return result


def _ensure_domain(d: Optional[Dict]) -> Dict:
    d = dict(d or {})
    d.setdefault("existing_plan", "")
    d.setdefault("progress", "")
    d.setdefault("goal_set", {})
    for k in ALLOWED_GOAL_KEYS:
        d["goal_set"].setdefault(k, "")
    d.setdefault("barrier", "")
    return d


def ensure_fixed_state_shape(state: Optional[Dict]) -> Dict:
    st = dict(state or {})
    st.setdefault("session", {})
    st["session"].setdefault("session_timestamp", "")
    st["session"].setdefault(
        "agenda",
        "Choose one domain to focus on: activity, meal/nutrition, or sleep.",
    )
    st.setdefault("allowed_domains", sorted(ALLOWED_DOMAINS))
    for dom in ALLOWED_DOMAINS:
        st[dom] = _ensure_domain(st.get(dom))
    return st


# ---------------- Normalization & parsing ----------------

STATE_OPEN_RE = re.compile(r"<\s*(_?STATE)\s*>", re.IGNORECASE)
STATE_CLOSE_RE = re.compile(r"<\s*/\s*(_?STATE)\s*>", re.IGNORECASE)


def _normalize_state_tags(s: str) -> str:
    s = STATE_OPEN_RE.sub("<STATE>", s)
    s = STATE_CLOSE_RE.sub("</STATE>", s)
    return s


def _to_ascii(s: str) -> str:
    if not isinstance(s, str):
        return s
    return (
        s.replace("ƒ?o", '"')
        .replace("ƒ??", '"')
        .replace("ƒ?T", "'")
        .replace("ƒ+'", "->")
        .replace("\u200b", "")
    )


def _sanitize_updates_text(body: str) -> str:
    s = _to_ascii(body or "")

    s = re.sub(r"\s*->\s*", "->", s)
    s = re.sub(r",\s*(?=(?:[A-Za-z_]+\s*->)|</STATE>)", "\n", s)
    s = re.sub(r"^[,\s]+", "", s)
    s = re.sub(r"[,\s]+$", "", s)

    s = re.sub(r"\bgoa?l[_\-\s]*set\b", "goal_set", s, flags=re.IGNORECASE)
    s = re.sub(r"\bexisting[_\-\s]*plan\b", "existing_plan", s, flags=re.IGNORECASE)
    s = re.sub(r"\bsession[_\-\s]*timestamp\b", "session_timestamp", s, flags=re.IGNORECASE)
    s = re.sub(r"\bbarriers\b", "barrier", s, flags=re.IGNORECASE)
    for k in ALLOWED_GOAL_KEYS:
        s = re.sub(fr"\b{k}\b", k, s, flags=re.IGNORECASE)
    for d in ALLOWED_DOMAINS:
        s = re.sub(fr"\b{d}\b", d, s, flags=re.IGNORECASE)

    return s


UPDATES_RE_ALL = re.compile(r"<STATE>\s*(?P<body>.*?)\s*</STATE>", re.DOTALL | re.IGNORECASE)


def _extract_updates_body(delta_output: Optional[Union[str, Dict, List]]) -> Optional[str]:
    if delta_output is None:
        return None
    if not isinstance(delta_output, str):
        try:
            delta_output = str(delta_output)
        except Exception:
            return None
    delta_output = _normalize_state_tags(delta_output)
    bodies = [m.group("body").strip() for m in UPDATES_RE_ALL.finditer(delta_output)]
    if bodies:
        return bodies[-1]
    return delta_output.strip() or None


def _validate_and_filter_deltas(raw_updates: List[Tuple[List[str], str]]) -> List[Tuple[List[str], str]]:
    cleaned = []
    for path, value in raw_updates:
        if not path:
            continue
        root = path[0]
        if root == "session":
            if len(path) == 2 and path[1] in ALLOWED_LEAVES["session"]:
                cleaned.append((path, value))
                continue
        if root in ALLOWED_DOMAINS:
            if len(path) == 2 and path[1] in ALLOWED_LEAVES[root]:
                cleaned.append((path, value))
                continue
            if len(path) == 3 and path[1] == "goal_set" and path[2] in ALLOWED_GOAL_KEYS:
                cleaned.append((path, value))
                continue
    return cleaned


def parse_and_clean_deltas(delta_output: Optional[Union[str, Dict, List]]) -> List[Tuple[List[str], str]]:
    body = _extract_updates_body(delta_output) or ""
    body = _sanitize_updates_text(body)

    if not body or body.upper() == "NONE":
        return []

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    raw_updates: List[Tuple[List[str], str]] = []
    for line in lines:
        if line.upper() == "NONE":
            continue
        if ":" not in line:
            continue
        path_str, val_str = line.split(":", 1)
        path_tokens = [p.strip() for p in path_str.split("->") if p.strip()]
        if not path_tokens:
            continue
        v = val_str.strip().rstrip(",")
        if not (len(v) >= 2 and v[0] in {'"', "'"} and v[-1] in {'"', "'"}):
            v = '"' + v.strip() + '"'
        value = v[1:-1]
        raw_updates.append((path_tokens, value))

    return _validate_and_filter_deltas(raw_updates)


# ---------------- State application ----------------


def apply_deltas(state: Optional[Dict], deltas: List[Tuple[List[str], str]]) -> Dict:
    st = ensure_fixed_state_shape(state)
    for path, value in deltas:
        if not path:
            continue
        node = st
        for key in path[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        leaf = path[-1]
        if path[0] == "session" and leaf in {"agenda", "session_timestamp"}:
            node[leaf] = value
            continue
        if path[0] in ALLOWED_DOMAINS:
            if leaf in {"existing_plan", "progress", "barrier"}:
                node[leaf] = value
                continue
            if len(path) == 3 and path[1] == "goal_set" and leaf in ALLOWED_GOAL_KEYS:
                node[leaf] = value
                continue

    return st


def apply_delta_text(state: Optional[Dict], delta_text: Optional[Union[str, Dict, List]]) -> Dict:
    return apply_deltas(state, parse_and_clean_deltas(delta_text))


def state_to_text(state: Optional[Dict]) -> str:
    return json.dumps(ensure_fixed_state_shape(state), ensure_ascii=False, indent=2)


def build_initial_cst(session_timestamp: str) -> Dict:
    state = ensure_fixed_state_shape({})
    state["session"]["session_timestamp"] = session_timestamp
    return state


def build_patch_messages(
    cst_state: Dict,
    chat_history_text: str | None = None,
    meta_text: str | None = None,
) -> List[Dict[str, str]]:
    cst_json = json.dumps(cst_state, ensure_ascii=False, indent=2)
    history_block = ""
    if chat_history_text:
        history_block = "Current session chat history:\n" + chat_history_text.strip() + "\n\n"
    system_text = GENERATOR_PROMPT_V1.strip()
    if meta_text:
        system_text = meta_text.strip() + "\n\n" + system_text
    user_text = (
        "Generate a prompt patch to guide the Coach Agent's next response\n"
        f"{history_block}"
        "CST (JSON):\n"
        f"{cst_json}"
    )
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]


def generate_prompt_patch(
    cst_state: Dict,
    chat_history_text: str | None = None,
    meta_text: str | None = None,
) -> str:
    if UI_TEST_MODE:
        return ""
    messages = build_patch_messages(
        cst_state,
        chat_history_text=chat_history_text,
        meta_text=meta_text,
    )
    return generator_agent.generate(messages)
