# prompt_helper_b.py
# Message-based builder for Agent B (extractor) + robust sanitizer & parser.

import json
import re
from typing import Dict, List, Tuple, Optional, Union

# ---------------- Fixed schema ----------------

ALLOWED_DOMAINS = {"activity", "nutrition", "sleep", "tracking"}
ALLOWED_GOAL_KEYS = {"Specific", "Measure", "Attainable", "Reward", "Timeframe"}
ALLOWED_LEAVES = {
    "session": {"agenda"},
    "activity": {"fact", "goal_set", "barrier"},
    "nutrition": {"fact", "goal_set", "barrier"},
    "sleep": {"fact", "goal_set", "barrier"},
    "tracking": {"fact", "goal_set", "barrier"},
}

def _is_none_like(s: Optional[str]) -> bool:
    if s is None:
        return True
    if not isinstance(s, str):
        s = str(s)
    return s.strip() == "" or s.strip().lower() in {"none", "null", "n/a"}

def _append_text(existing: Optional[str], new: str, sep: str = "; ", max_len: Optional[int] = None) -> str:
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
        # duplicate check: split by separators and compare case-insensitively
        tokens = [t.strip().lower() for t in re.split(r"[;|,/]\s*", ex) if t.strip()]
        if new.lower() in tokens:
            result = ex  # already present
        else:
            # simple join with sep, avoid double separators
            if ex.endswith(tuple([";", "|", ",", "/"])):
                result = ex + " " + new
            else:
                result = ex + sep + new

    if max_len is not None and len(result) > max_len:
        result = result[:max_len].rstrip()
    return result


def _ensure_domain(d: Optional[Dict]) -> Dict:
    d = dict(d or {})
    d.setdefault("fact", "None")
    d.setdefault("goal_set", {})
    for k in ALLOWED_GOAL_KEYS:
        d["goal_set"].setdefault(k, "None")
    d.setdefault("barrier", "None")
    return d

def ensure_fixed_state_shape(state: Optional[Dict]) -> Dict:
    st = dict(state or {})
    st.setdefault("week", 1)
    st.setdefault("day", 1)
    st.setdefault("patient", {})
    st.setdefault("status", {})
    st.setdefault("session", {})
    st["session"].setdefault(
        "agenda",
        "Choose one domain to focus on: activity, meal/nutrition, or tracking habits",
    )
    for dom in ALLOWED_DOMAINS:
        st[dom] = _ensure_domain(st.get(dom))
    return st

# ---------------- Safe user text extraction ----------------

def _extract_latest_user_text(user_answer: Union[str, Dict, List]) -> str:
    if isinstance(user_answer, str):
        return user_answer.strip()
    if isinstance(user_answer, dict):
        c = user_answer.get("content", "")
        return c.strip() if isinstance(c, str) else str(c).strip()
    if isinstance(user_answer, list):
        for m in reversed(user_answer):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content", "")
                return c.strip() if isinstance(c, str) else str(c).strip()
        for m in reversed(user_answer):
            if isinstance(m, dict) and "content" in m:
                c = m.get("content", "")
                return c.strip() if isinstance(c, str) else str(c).strip()
        if user_answer:
            return str(user_answer[-1]).strip()
    return str(user_answer).strip()

# ---------------- Agent B: messages & examples ----------------

PROMPT_EXTRACT = """\
ROLE
You are a careful information extractor. Your job is to turn the user's latest answer into STATE updates.

TASK
Output ONLY a <STATE> block with one update per line, or 'NONE' if there are no updates.

STATE SCHEMA (fixed; you only produce deltas):
- Domains: activity, nutrition, sleep, tracking
- Allowed paths:
    session->agenda
    <domain>->fact
    <domain>->goal_set->Specific
    <domain>->goal_set->Measure
    <domain>->goal_set->Attainable
    <domain>->goal_set->Reward
    <domain>->goal_set->Timeframe
    <domain>->barrier

FORMAT (strict)
- Use ASCII arrow '->' (not Unicode).
- One update per line inside <STATE>...</STATE>.
- Value is in ASCII quotes.
- If NO updates, write exactly ONE line: NONE
"""

# Clean, line-by-line examples in the target format.
EXAMPLES_B = [
    (
        # User message
        "I wake up at 9 AM and have a yogurt as breakfast in the morning at 10 AM",
        # Assistant (target) format
        "<STATE>\n"
        "nutrition-> fact: \"yogurt as breakfast at 10 AM\"\n"
        "sleep> fact: \"wake up at 9 AM\"\n"
        "</STATE>"
    ),
    (
        # User message
        "I'll log breakfast each day at 8 AM for a week. I belive I can do so",
        # Assistant (target) format
        "<STATE>\n"
        "tracking->goal_set->Specific: \"Log breakfast\"\n"
        "tracking->goal_set->Attainable: \"Confident\"\n"
        "tracking->goal_set->Timeframe: \"Daily at 8 AM for 7 days\"\n"
        "tracking->fact: \"Plan to use an app at 8 AM\"\n"
        "</STATE>"
    ),
    (
        "Let's focus on steps—walk 15 minutes after lunch on weekdays. You can have a piece of chocolate afte that",
        "<STATE>\n"
        "activity->goal_set->Specific: \"Walk 15 minutes after lunch\"\n"
        "activity->goal_set->Measure: \"15 minutes\"\n"
        "activity->goal_set->Reasure: \"piece of chocolate\"\n"
        "activity->goal_set->Timeframe: \"Weekdays this week\"\n"
        "</STATE>"
    ),
    (
        "I'm often too tired after work to cook—maybe prep on Sunday? I will spend 30 minutes on it",
        "<STATE>\n"
        "nutrition->barrier: \"Too tired to cook after work\"\n"
        "nutrition-> goal_set-> Specific: \"Plan to meal prep on Sunday\"\n"
        "nutrition-> goal_set-> Measure: \"30 minutes\"\n"
        "</STATE>"
    ),
]

def build_extraction_messages(user_answer: Union[str, Dict, List], include_examples: bool = True) -> List[Dict[str, str]]:
    msgs: List[Dict[str,str]] = [{"role":"system","content":PROMPT_EXTRACT.strip()}]
    if include_examples:
        for u,a in EXAMPLES_B:
            msgs.append({"role":"user","content":u})
            msgs.append({"role":"assistant","content":a})
    msgs.append({"role":"user","content":_extract_latest_user_text(user_answer)})
    return msgs

# Back-compat string builder (renders messages to a Qwen-style chat string)
def _render_messages_to_chat(messages: List[Dict[str, str]], start_tag="<|im_start|>", end_tag="<|im_end|>") -> str:
    parts = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        tag = "system" if role == "system" else ("assistant" if role == "assistant" else "user")
        parts.append(f"{start_tag}{tag}\n{content}{end_tag}\n")
    parts.append(f"{start_tag}assistant\n")
    return "".join(parts)

def build_extraction_prompt(user_answer: Union[str, Dict, List]) -> str:
    return _render_messages_to_chat(build_extraction_messages(user_answer, include_examples=True))

# ---------------- Normalization & parsing ----------------

# Accept a few bad tag variants
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
        s.replace("“", '"').replace("”", '"')
         .replace("’", "'").replace("—", "-").replace("–", "-")
         .replace("→", "->").replace("➔", "->").replace("→", "->")
         .replace("—>", "->").replace("–>", "->")
         .replace("\u200b", "")
    )

def _sanitize_updates_text(body: str) -> str:
    s = _to_ascii(body or "")

    # Normalize arrow spacing
    s = re.sub(r"\s*->\s*", "->", s)

    # Many models separate fields by commas; convert commas between fields into newlines,
    # but only when followed by another path-like token or a closing tag.
    s = re.sub(r",\s*(?=(?:[A-Za-z_]+\s*->)|</STATE>)", "\n", s)

    # Remove leading/trailing commas and stray separators
    s = re.sub(r"^[,\s]+", "", s)
    s = re.sub(r"[,\s]+$", "", s)

    # Canonical casing & key normalization
    s = re.sub(r"\bgoa?l[_\-\s]*set\b", "goal_set", s, flags=re.IGNORECASE)
    s = re.sub(r"\brecord\s*ing\b", "fact", s, flags=re.IGNORECASE)
    for k in ALLOWED_GOAL_KEYS:
        s = re.sub(fr"\b{k}\b", k, s, flags=re.IGNORECASE)
    for d in ALLOWED_DOMAINS:
        s = re.sub(fr"\b{d}\b", d, s, flags=re.IGNORECASE)

    return s

UPDATES_RE_ALL = re.compile(
    r"<STATE>\s*(?P<body>.*?)\s*</STATE>",
    re.DOTALL | re.IGNORECASE
)

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
    # If there is no STATE block at all, assume raw lines
    return delta_output.strip() or None

def _validate_and_filter_deltas(raw_updates: List[Tuple[List[str], str]]) -> List[Tuple[List[str], str]]:
    cleaned = []
    for path, value in raw_updates:
        if not path:
            continue
        root = path[0]
        if root == "session":
            if len(path) == 2 and path[1] in ALLOWED_LEAVES["session"]:
                cleaned.append((path, value)); continue
        if root in ALLOWED_DOMAINS:
            if len(path) == 2 and path[1] in ALLOWED_LEAVES[root]:
                cleaned.append((path, value)); continue
            if len(path) == 3 and path[1] == "goal_set" and path[2] in ALLOWED_GOAL_KEYS:
                cleaned.append((path, value)); continue
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
        # Wrap unquoted values in ASCII quotes
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
        if path[0] == "session" and leaf == "agenda":
            node[leaf] = value; continue
        if path[0] in ALLOWED_DOMAINS:
            if leaf in {"recording", "barrier"}:
                node[leaf] = _append_text(node.get(leaf), value, sep="; ", max_len=1000)
                continue
            # goal_set leaves: path is domain -> goal_set -> <leaf>.
            if len(path) == 3 and path[1] == "goal_set" and leaf in ALLOWED_GOAL_KEYS:
                node[leaf] = _append_text(node.get(leaf), value, sep="; ", max_len=500)
                continue

    return st

# --------------- Utilities ---------------

def apply_delta_text(state: Optional[Dict], delta_text: Optional[Union[str, Dict, List]]) -> Dict:
    return apply_deltas(state, parse_and_clean_deltas(delta_text))

def state_to_text(state: Optional[Dict]) -> str:
    return json.dumps(ensure_fixed_state_shape(state), ensure_ascii=False, indent=2)
