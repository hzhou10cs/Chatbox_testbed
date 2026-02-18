#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
continuity_eval.py

Batch-evaluate cross-session continuity (pairwise progression) for multi-user 5-session logs.

Directory layout (example):
  ../user_data
    /user_name1
      /chats
        chat1.json
        chat2.json
        chat3.json
        chat4.json
        chat5.json
        chat_index.json  (ignored)
      /coach_state_tracker  (ignored)
      /session_report       (ignored)
      user_info.json        (ignored)
    /user_name2
      ...

Outputs (example):
  ../out_continuity_eval/
    batch_input.jsonl
    batch_output.jsonl
    batch_error.jsonl (if any)
    request_index.json
    results.jsonl
    results.xlsx
    readable/
      combined_readable.json
      per_item/
        <custom_id>.json

Requires:
  pip install --upgrade openai pandas openpyxl
Env:
  OPENAI_API_KEY=...
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openai import OpenAI


# -------------------------
# Prompt (Cross-session Continuity Rubric)
# -------------------------
CONTINUITY_JUDGE_SYSTEM_PROMPT = r"""
You are an evaluation judge for a multi-session behavioral-health coaching dialogue system.

Task
Given ONE user's full five-session transcript in JSON, evaluate cross-session continuity as forgetting-related failures.
You must identify and count four event types across the full trajectory, normalize counts by assistant-turns,
and output the rates and a continuity score based on a fixed penalty formula.

Continuity definition
Continuity means the assistant preserves and correctly reuses previously established user state across sessions,
without restart-style re-elicitation or state drift.

Event types (count across the full five-session trajectory)

(1) RQ = Restart Question
The assistant re-asks information that was already established earlier (schedule, reward, preference, barrier, plan detail),
WITHOUT a user-initiated recap request and WITHOUT a clear reason that the information has changed.
Examples (non-exhaustive): re-asking bedtime/wake time after it was set; re-asking preferred activity after it was chosen;
re-asking a confirmed barrier; re-asking the reward after it was agreed.

Do NOT count as RQ when:
- The user explicitly asks for recap/confirmation ("can you remind me what we decided?")
- The user indicates a change or uncertainty ("I forgot what we set", "maybe it's different now")
- The assistant asks a clarification that adds new measurable detail that was not previously established
  (this is refinement, not a restart question)

(2) RB = Rollback / Contradiction
The assistant reverts to an obsolete plan version OR states content that contradicts previously confirmed information.
This includes: switching back to a discarded goal, forgetting a confirmed schedule, contradicting a stated constraint,
or claiming the user agreed to something they previously rejected.

Critical non-double-counting rule:
If the user explicitly challenges the inconsistency within the next ONE or TWO user turns (a UC event),
attribute the incident to UC instead of counting RB. In that case, record RB as "suppressed_by_uc": true
and do NOT increment RB count.

(3) CD = Constraint Drop
The assistant proposes or reintroduces an option that violates a user-confirmed constraint or preference,
even if it does not explicitly re-ask the constraint. This indicates state drift.
Examples: proposing late-night workouts after user confirmed they cannot exercise at night; suggesting a food plan
that violates a confirmed dietary restriction; suggesting an approach that the user explicitly dislikes.

Do NOT count as CD when:
- The user has explicitly relaxed/changed the constraint later
- The assistant offers an option as a contrast while clearly acknowledging the constraint
  (e.g., "since you said you cannot do evenings, we will avoid X")

(4) UC = User Challenge
The user explicitly challenges the assistant’s memory or consistency, e.g.:
- pointing out repeated questioning ("you already asked me that")
- questioning whether the assistant remembers ("do you remember what I said?")
- calling out contradiction ("that’s not what we agreed")
- accusing the assistant of restarting or forgetting

Turn indexing and scope
- Evaluate over the entire multi-session trajectory in chronological order.
- Only assistant turns contribute to T_u (total assistant turns).
- User turns can trigger UC, and can be used as evidence for whether an earlier assistant statement was incorrect.

What to output
Return VALID JSON only. No markdown. No extra text.

Schema (EXACT):
{
  "meta": {
    "total_sessions": 5,
    "total_turns_all_roles": 0,
    "total_assistant_turns": 0
  },
  "events": [
    {
      "event_type": "RQ|RB|CD|UC",
      "assistant_turn_index": 0,
      "session_id": 0,
      "turn_id_in_session": 0,
      "short_desc": "",
      "suppressed_by_uc": false
    }
  ],
  "counts": {
    "RQ": 0,
    "RB": 0,
    "CD": 0,
    "UC": 0
  },
  "rates": {
    "r_RQ": 0.0,
    "r_RB": 0.0,
    "r_CD": 0.0,
    "r_UC": 0.0
  },
  "penalty": {
    "weighted_penalty": 0.0,
    "contrib_RQ": 0.0,
    "contrib_RB": 0.0,
    "contrib_CD": 0.0,
    "contrib_UC": 0.0
  },
  "score": 0.0
}

Counting rules
1) total_assistant_turns = number of assistant messages across all sessions.
2) N_u^x is the count of events of type x in "events", with the exception that:
   - RB events with suppressed_by_uc=true MUST NOT be counted toward counts.RB.
3) rates:
   r_RQ = counts.RQ / total_assistant_turns
   r_RB = counts.RB / total_assistant_turns
   r_CD = counts.CD / total_assistant_turns
   r_UC = counts.UC / total_assistant_turns
   If total_assistant_turns == 0, all rates are 0.0.

Penalty and score
- contrib_UC = 3 * r_UC
- contrib_RQ = 1 * r_RQ
- contrib_RB = 1 * r_RB
- contrib_CD = 1 * r_CD
- weighted_penalty = contrib_UC + contrib_RQ + contrib_RB + contrib_CD
- score = max(0, 100 - 100 * weighted_penalty)

Event identification guidance (be strict and conservative)
- Prefer NOT to create an event unless evidence is clear.
- RQ requires that the information was established earlier; do not assume it was established if ambiguous.
- CD requires an actually confirmed constraint/preference earlier and a later suggestion that violates it.
- UC requires explicit user challenge language; mild disagreement without reference to memory/consistency is not UC.
- Apply the RB suppression rule exactly: if a UC occurs within the next 1-2 user turns after an RB-like assistant statement,
  create a UC event and create the RB event with suppressed_by_uc=true but do not count RB.

Output quality constraints
- assistant_turn_index must be a 0-based index over assistant turns only (chronological over all sessions).
- session_id is the session number from the input (use 1..5 if available; otherwise infer sequentially).
- turn_id_in_session is the assistant turn index within that session (0-based).
- short_desc should be <= 20 words and describe the forgetting symptom.
""".strip()


# -------------------------
# Utilities (Pydantic-safe, JSON helpers)
# -------------------------
def as_dict(obj: Any) -> Dict[str, Any]:
    """Convert SDK Pydantic objects to dict safely."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):  # pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):        # pydantic v1
        return obj.dict()
    return {}


def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    # handle possible UTF-8 BOM on Windows
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def json_canonical_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def extract_output_text_from_responses_body(body: Dict[str, Any]) -> str:
    """
    Best-effort extraction of assistant output text from a Responses API response object.
    Batch output returns raw JSON, so we parse typical 'output' structures.
    """
    if isinstance(body, dict) and isinstance(body.get("output_text"), str):
        return body["output_text"]

    out_parts: List[str] = []
    output = body.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message" and item.get("role") == "assistant":
                content = item.get("content", [])
                if isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                            t = c.get("text")
                            if isinstance(t, str) and t:
                                out_parts.append(t)
    if out_parts:
        return "\n".join(out_parts)

    return json.dumps(body, ensure_ascii=False)


def try_parse_json(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Parse JSON robustly; if it fails, return error string.
    """
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# -------------------------
# Data discovery
# -------------------------
# -------------------------
# Data discovery
# -------------------------
def discover_users(user_data_dir: Path) -> List[Path]:
    return [p for p in user_data_dir.iterdir() if p.is_dir()]


def discover_chat_all_for_user(user_dir: Path) -> Optional[Path]:
    """
    Prefer pre-built multi-session file:
      user_dir/chats/chat_all.json
    Returns None if not found.
    """
    p = user_dir / "chats" / "chat_all.json"
    return p if p.exists() and p.is_file() else None


# -------------------------
# Batch input builder
# -------------------------
# -------------------------
def build_batch_input_jsonl(
    user_data_dir: Path,
    out_jsonl: Path,
    request_index_path: Path,
    model: str,
    system_prompt: str,
    reasoning_effort: str,
    store: bool = False,
    user_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build batch input jsonl for /v1/responses and write request_index.json
    Returns request_index list of dicts.
    """
    users = discover_users(user_data_dir)
    if user_filter:
        users = [u for u in users if user_filter.lower() in u.name.lower()]

    request_index: List[Dict[str, Any]] = []
    lines_written = 0

    with out_jsonl.open("w", encoding="utf-8") as f:
        for user_dir in users:
            user_id = user_dir.name
            chat_all_path = discover_chat_all_for_user(user_dir)
            if not chat_all_path:
                continue

            custom_id = user_id  # one request per user trajectory

            req_meta = {
                "custom_id": custom_id,
                "user_id": user_id,
                "chat_all_file": str(chat_all_path),
            }
            request_index.append(req_meta)

            chat_all_json = load_json(chat_all_path)

            user_payload = (
                "Evaluate cross-session continuity on the full five-session trajectory.\\n\\n"
                "<CHAT_ALL_JSON>\\n"
                f"{json_canonical_dumps(chat_all_json)}\\n"
                "</CHAT_ALL_JSON>\\n"
            )

            # IMPORTANT: Do NOT include temperature for gpt-5.2-pro with reasoning != none.
            body = {
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "reasoning": {"effort": reasoning_effort},
                "store": store,
            }

            line = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": body,
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
            lines_written += 1

    request_index_path.write_text(json.dumps(request_index, ensure_ascii=False, indent=2), encoding="utf-8")

    if lines_written == 0:
        raise RuntimeError(f"No requests built. Check user_data_dir={user_data_dir} and chat files.")

    return request_index


# -------------------------
# Batch polling + download
# -------------------------
def poll_batch_until_done(client: OpenAI, batch_id: str, poll_s: int = 15) -> Any:
    terminal = {"completed", "failed", "expired", "cancelled"}
    while True:
        b = client.batches.retrieve(batch_id)
        status = b.status
        rc = getattr(b, "request_counts", None)
        print(f"[batch] {batch_id} status={status} request_counts={rc}")
        if status in terminal:
            return b
        time.sleep(poll_s)


def download_file_content(client: OpenAI, file_id: str, out_path: Path) -> None:
    resp = client.files.content(file_id)
    # newer SDK returns a response-like object with .text for text files
    if hasattr(resp, "text") and resp.text is not None:
        out_path.write_text(resp.text, encoding="utf-8")
        return
    # fallback bytes
    data = getattr(resp, "content", None)
    if data is None:
        data = str(resp).encode("utf-8")
    out_path.write_bytes(data)


# -------------------------
# Parse batch output + write results
# -------------------------
def parse_batch_output_jsonl(batch_output_path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line in batch_output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)

        custom_id = obj.get("custom_id")
        err = obj.get("error")
        resp = obj.get("response") or {}
        status_code = resp.get("status_code")
        body = resp.get("body") if isinstance(resp, dict) else None
        body = body if isinstance(body, dict) else {}

        output_text = ""
        parsed = None
        parse_error = None

        if err is None and status_code == 200:
            output_text = extract_output_text_from_responses_body(body)
            parsed, parse_error = try_parse_json(output_text)
        else:
            parse_error = f"request_error: {err or body.get('error', {})}"

        records.append(
            {
                "custom_id": custom_id,
                "status_code": status_code,
                "error": err,
                "output_text": output_text,
                "parsed": parsed,
                "parse_error": parse_error,
                "model": body.get("model"),
                "system_fingerprint": body.get("system_fingerprint"),
            }
        )

    return records


def flatten_continuity(parsed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Flatten the continuity judge JSON to simple scalar fields for xlsx.
    """
    out: Dict[str, Any] = {
        "total_sessions": None,
        "total_turns_all_roles": None,
        "total_assistant_turns": None,
        "count_RQ": None,
        "count_RB": None,
        "count_CD": None,
        "count_UC": None,
        "r_RQ": None,
        "r_RB": None,
        "r_CD": None,
        "r_UC": None,
        "weighted_penalty": None,
        "contrib_RQ": None,
        "contrib_RB": None,
        "contrib_CD": None,
        "contrib_UC": None,
        "score": None,
    }
    if not isinstance(parsed, dict):
        return out

    meta = parsed.get("meta", {})
    if isinstance(meta, dict):
        out["total_sessions"] = meta.get("total_sessions")
        out["total_turns_all_roles"] = meta.get("total_turns_all_roles")
        out["total_assistant_turns"] = meta.get("total_assistant_turns")

    counts = parsed.get("counts", {})
    if isinstance(counts, dict):
        out["count_RQ"] = counts.get("RQ")
        out["count_RB"] = counts.get("RB")
        out["count_CD"] = counts.get("CD")
        out["count_UC"] = counts.get("UC")

    rates = parsed.get("rates", {})
    if isinstance(rates, dict):
        out["r_RQ"] = rates.get("r_RQ")
        out["r_RB"] = rates.get("r_RB")
        out["r_CD"] = rates.get("r_CD")
        out["r_UC"] = rates.get("r_UC")

    penalty = parsed.get("penalty", {})
    if isinstance(penalty, dict):
        out["weighted_penalty"] = penalty.get("weighted_penalty")
        out["contrib_RQ"] = penalty.get("contrib_RQ")
        out["contrib_RB"] = penalty.get("contrib_RB")
        out["contrib_CD"] = penalty.get("contrib_CD")
        out["contrib_UC"] = penalty.get("contrib_UC")

    out["score"] = parsed.get("score")
    return out


def write_readable_outputs(
    out_dir: Path,
    request_index: List[Dict[str, Any]],
    records: List[Dict[str, Any]],
) -> None:
    readable_dir = out_dir / "readable"
    per_item_dir = readable_dir / "per_item"
    safe_mkdir(per_item_dir)

    idx_map = {r["custom_id"]: r for r in request_index}
    combined: Dict[str, Any] = {}

    for rec in records:
        cid = rec["custom_id"]
        meta = idx_map.get(cid, {})
        item = {
            "meta": meta,
            "status_code": rec["status_code"],
            "parse_error": rec["parse_error"],
            "judge": rec["parsed"],
            "output_text": rec["output_text"],  # keep for audit/debug
            "model": rec["model"],
            "system_fingerprint": rec["system_fingerprint"],
        }

        # per-item file
        (per_item_dir / f"{cid}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        user_id = meta.get("user_id", "UNKNOWN_USER")
        combined[user_id] = item

    (readable_dir / "combined_readable.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", default="../user_data", help="Root user_data directory")
    ap.add_argument("--out_dir", default="../out_continuity_eval", help="Output directory")
    ap.add_argument("--model", default="gpt-5.2-pro", help="Model id (default: gpt-5.2-pro)")
    ap.add_argument("--prompt_file", default="", help="Optional: system prompt file override")
    ap.add_argument("--reasoning_effort", default="high", choices=["none", "low", "medium", "high", "xhigh"],
                    help="Reasoning effort (use high/xhigh for reliability). Note: temperature is NOT used.")
    ap.add_argument("--poll_s", type=int, default=15, help="Batch status polling interval (seconds)")
    ap.add_argument("--user_filter", default="", help="Optional: only evaluate users whose folder name contains this substring")
    args = ap.parse_args()

    user_data_dir = Path(args.user_data_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    safe_mkdir(out_dir)

    system_prompt = CONTINUITY_JUDGE_SYSTEM_PROMPT
    if args.prompt_file:
        system_prompt = read_text(Path(args.prompt_file).expanduser().resolve()).strip()

    batch_input_jsonl = out_dir / "batch_input.jsonl"
    request_index_path = out_dir / "request_index.json"

    print(f"[1/6] Building batch input jsonl -> {batch_input_jsonl}")
    request_index = build_batch_input_jsonl(
        user_data_dir=user_data_dir,
        out_jsonl=batch_input_jsonl,
        request_index_path=request_index_path,
        model=args.model,
        system_prompt=system_prompt,
        reasoning_effort=args.reasoning_effort,
        store=False,
        user_filter=(args.user_filter or None),
    )
    print(f"  Prepared {len(request_index)} requests. Saved index -> {request_index_path}")

    client = OpenAI()

    print("[2/6] Uploading batch input file (purpose='batch') ...")
    batch_input_file = client.files.create(file=batch_input_jsonl.open("rb"), purpose="batch")
    batch_input_file_id = batch_input_file.id
    print(f"  Uploaded: file_id={batch_input_file_id}")

    print("[3/6] Creating batch (endpoint='/v1/responses', completion_window='24h') ...")
    batch = client.batches.create(
        input_file_id=batch_input_file_id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={"job": "cross-session-continuity-eval", "model": args.model},
    )
    batch_id = batch.id
    print(f"  Batch created: batch_id={batch_id}")

    print("[4/6] Polling until batch completes ...")
    batch_final = poll_batch_until_done(client, batch_id, poll_s=args.poll_s)
    status = batch_final.status
    print(f"  Final status: {status}")

    output_file_id = batch_final.output_file_id
    error_file_id = batch_final.error_file_id

    if not output_file_id:
        print("No output_file_id. Likely 0 successful requests.")
        print("request_counts:", batch_final.request_counts)
        print("error_file_id:", error_file_id)
        if error_file_id:
            err_path = out_dir / "batch_error.jsonl"
            download_file_content(client, error_file_id, err_path)
            print(f"Downloaded errors -> {err_path}")
        return 2

    print("[5/6] Downloading output file(s) ...")
    batch_output_path = out_dir / "batch_output.jsonl"
    download_file_content(client, output_file_id, batch_output_path)
    print(f"  Saved: {batch_output_path}")

    if error_file_id:
        batch_error_path = out_dir / "batch_error.jsonl"
        download_file_content(client, error_file_id, batch_error_path)
        print(f"  Saved: {batch_error_path}")

    print("[6/6] Parsing outputs and writing results ...")
    records = parse_batch_output_jsonl(batch_output_path)

    # Load request index mapping
    idx_map = {r["custom_id"]: r for r in request_index}

    # Write results.jsonl (enriched with user/pair info + flattened scores)
    results_jsonl = out_dir / "results.jsonl"
    enriched: List[Dict[str, Any]] = []
    with results_jsonl.open("w", encoding="utf-8") as f:
        for rec in records:
            meta = idx_map.get(rec["custom_id"], {})
            flat = flatten_continuity(rec["parsed"])
            out = {**meta, **rec, **flat}
            enriched.append(out)
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"  Saved: {results_jsonl}")

    # Write results.xlsx (one row per user)
    df = pd.DataFrame(
        [
            {
                "user_id": r.get("user_id"),
                "custom_id": r.get("custom_id"),
                "chat_all_file": r.get("chat_all_file"),
                "status_code": r.get("status_code"),
                "parse_error": r.get("parse_error"),
                "total_sessions": r.get("total_sessions"),
                "total_turns_all_roles": r.get("total_turns_all_roles"),
                "total_assistant_turns": r.get("total_assistant_turns"),
                "count_RQ": r.get("count_RQ"),
                "count_RB": r.get("count_RB"),
                "count_CD": r.get("count_CD"),
                "count_UC": r.get("count_UC"),
                "r_RQ": r.get("r_RQ"),
                "r_RB": r.get("r_RB"),
                "r_CD": r.get("r_CD"),
                "r_UC": r.get("r_UC"),
                "contrib_RQ": r.get("contrib_RQ"),
                "contrib_RB": r.get("contrib_RB"),
                "contrib_CD": r.get("contrib_CD"),
                "contrib_UC": r.get("contrib_UC"),
                "weighted_penalty": r.get("weighted_penalty"),
                "score": r.get("score"),
                "model": r.get("model"),
                "system_fingerprint": r.get("system_fingerprint"),
            }
            for r in enriched
        ]
    ).sort_values(by=["user_id"])

    xlsx_path = out_dir / "results.xlsx"
    df.to_excel(xlsx_path, index=False)
    print(f"  Saved: {xlsx_path}")

    # Write readable JSON outputs
    write_readable_outputs(out_dir, request_index, records)
    print(f"  Saved readable JSON -> {out_dir / 'readable'}")

    print("\nDone.")
    print(f"Batch id: {batch_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
