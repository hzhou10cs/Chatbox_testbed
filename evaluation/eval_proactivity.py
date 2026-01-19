#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eval_proactivity.py

Batch-evaluate PROACTIVITY (turn-level ordinal scores) for multi-user session logs.

Reads:
  ../user_data/<user_id>/chats/chat1.json ... chatN.json (chat_index.json ignored)

Writes:
  ../out_proactivity_eval/
    batch_input.jsonl
    batch_output.jsonl
    batch_error.jsonl (if any)
    request_index.json
    results.jsonl              (one row per session; includes parsed judge output)
    results_turns.xlsx         (one row per assistant turn; for plotting)
    results_sessions.xlsx      (one row per session; summary metrics)
    readable/
      combined_readable.json
      per_item/<custom_id>.json

Notes:
- Uses /v1/responses via Batch API.
- Avoids temperature (gpt-5.2-pro rejects it with reasoning != none).
- Avoids .get() on Batch objects (pydantic): uses attributes.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openai import OpenAI


# -------------------------
# Proactivity judge prompt
# -------------------------
DEFAULT_PROACTIVITY_SYSTEM_PROMPT = r"""
You are an evaluation judge for a behavioral-health coaching dialogue system.

Task:
Given ONE full session transcript in JSON, score PROACTIVITY for EACH assistant turn.
Proactivity means the assistant initiates agenda-advancing moves without requiring an explicit user request.

What counts as agenda advancement (examples):
- Eliciting next required information to make progress (e.g., missing SMART element: specific/measurable/achievable/relevant/time-bound)
- Clarifying barriers, constraints, or feasibility
- Confirming a commitment, next step, or implementation details
- Proposing a concrete next action grounded in the user's context

What does NOT count:
- Generic encouragement or praise that does not move the plan forward
- Purely reactive answers that only address the user's explicit question without adding next-step advancement
- Repeating prior content without new agenda advancement

Key judgment:
For each assistant turn, decide whether the assistant goes beyond responding to the user's immediate prompt.
If the user explicitly requests advice/next steps and the assistant only complies, it is less proactive.
If the assistant advances the agenda without being asked, it is more proactive.

Scoring (ordinal 0/1/2 per assistant turn):
0 = purely reactive / minimal; answers only what was asked; no agenda-advancing move
1 = weakly proactive; some agenda advancement but limited, indirect, or only minor beyond user request
2 = clearly proactive; explicit agenda advancement without user prompting; moves the session forward

Output requirements:
- Output VALID JSON only. No markdown, no extra text.
- Provide an entry for EVERY assistant turn in chronological order.
- Use EXACT schema:

{
  "assistant_turns": [
    {
      "assistant_turn_index": 1,
      "score": 0,
      "is_unprompted_agenda_advancing": 0,
      "agenda_move_type": "none|missing_smart|clarify_barrier|confirm_commitment|propose_next_step|other",
      "evidence": {"user_prompted": 0, "notes": ""}
    }
  ],
  "session_summary": {
    "num_assistant_turns": 0,
    "num_score2": 0,
    "num_score1_or_2": 0,
    "rate_unprompted_agenda_advancing": 0.0,
    "notes": ""
  }
}

Notes:
- assistant_turn_index counts assistant messages only (1..K).
- is_unprompted_agenda_advancing=1 iff the assistant advances the agenda WITHOUT an explicit user request.
- evidence.user_prompted=1 iff the user explicitly asked for advice/next steps or directly requested the agenda move.
""".strip()


# -------------------------
# Helpers
# -------------------------
CHAT_FILE_RE = re.compile(r"^chat(\d+)\.json$", re.IGNORECASE)


def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")  # tolerate BOM
    return json.loads(raw)


def json_canonical_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_output_text_from_responses_body(body: Dict[str, Any]) -> str:
    # Some SDK variants include output_text; batch raw body may not.
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
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def discover_users(user_data_dir: Path) -> List[Path]:
    return [p for p in user_data_dir.iterdir() if p.is_dir()]


def discover_chats_for_user(user_dir: Path) -> List[Tuple[int, Path]]:
    chats_dir = user_dir / "chats"
    if not chats_dir.exists():
        return []
    out: List[Tuple[int, Path]] = []
    for p in chats_dir.iterdir():
        if not p.is_file():
            continue
        if p.name.lower() == "chat_index.json":
            continue
        m = CHAT_FILE_RE.match(p.name)
        if m:
            out.append((int(m.group(1)), p))
    out.sort(key=lambda x: x[0])
    return out


def poll_batch_until_done(client: OpenAI, batch_id: str, poll_s: int = 15) -> Any:
    terminal = {"completed", "failed", "expired", "cancelled"}
    while True:
        b = client.batches.retrieve(batch_id)
        print(f"[batch] {batch_id} status={b.status} request_counts={getattr(b, 'request_counts', None)}")
        if b.status in terminal:
            return b
        time.sleep(poll_s)


def download_file_content(client: OpenAI, file_id: str, out_path: Path) -> None:
    resp = client.files.content(file_id)
    if hasattr(resp, "text") and resp.text is not None:
        out_path.write_text(resp.text, encoding="utf-8")
        return
    data = getattr(resp, "content", None)
    if data is None:
        data = str(resp).encode("utf-8")
    out_path.write_bytes(data)


# -------------------------
# Batch input builder
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
    users = discover_users(user_data_dir)
    if user_filter:
        users = [u for u in users if user_filter.lower() in u.name.lower()]

    request_index: List[Dict[str, Any]] = []
    lines_written = 0

    with out_jsonl.open("w", encoding="utf-8") as f:
        for user_dir in users:
            user_id = user_dir.name
            chats = discover_chats_for_user(user_dir)
            if not chats:
                continue

            for sess_idx, chat_path in chats:
                custom_id = f"{user_id}__s{sess_idx}"
                meta = {
                    "custom_id": custom_id,
                    "user_id": user_id,
                    "session_id": sess_idx,
                    "file_path": str(chat_path),
                }
                request_index.append(meta)

                session_json = load_json(chat_path)
                user_payload = (
                    "Score proactivity for each assistant turn in this single session.\n\n"
                    "<SESSION_JSON>\n"
                    f"{json_canonical_dumps(session_json)}\n"
                    "</SESSION_JSON>\n"
                )

                # IMPORTANT: do NOT include temperature.
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
        raise RuntimeError(f"No requests built. Check user_data_dir={user_data_dir}")

    return request_index


# -------------------------
# Output parsing
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


def write_readable_outputs(out_dir: Path, request_index: List[Dict[str, Any]], records: List[Dict[str, Any]]) -> None:
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
            "output_text": rec["output_text"],
            "model": rec["model"],
            "system_fingerprint": rec["system_fingerprint"],
        }

        (per_item_dir / f"{cid}.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")

        user_id = meta.get("user_id", "UNKNOWN_USER")
        session_id = str(meta.get("session_id", "UNKNOWN_SESSION"))
        combined.setdefault(user_id, {})
        combined[user_id][session_id] = item

    (readable_dir / "combined_readable.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def flatten_session_and_turns(
    request_index: List[Dict[str, Any]],
    records: List[Dict[str, Any]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      sessions_df: one row per session (user_id, session_id, summary metrics)
      turns_df: one row per assistant turn
    """
    idx_map = {r["custom_id"]: r for r in request_index}

    session_rows: List[Dict[str, Any]] = []
    turn_rows: List[Dict[str, Any]] = []

    for rec in records:
        cid = rec["custom_id"]
        meta = idx_map.get(cid, {})
        user_id = meta.get("user_id")
        session_id = meta.get("session_id")
        file_path = meta.get("file_path")

        parsed = rec.get("parsed")
        if not isinstance(parsed, dict):
            session_rows.append({
                "user_id": user_id,
                "session_id": session_id,
                "custom_id": cid,
                "file_path": file_path,
                "status_code": rec.get("status_code"),
                "parse_error": rec.get("parse_error"),
                "num_assistant_turns": None,
                "num_score2": None,
                "num_score1_or_2": None,
                "rate_unprompted_agenda_advancing": None,
                "notes": None,
                "model": rec.get("model"),
                "system_fingerprint": rec.get("system_fingerprint"),
            })
            continue

        st = parsed.get("session_summary", {}) if isinstance(parsed.get("session_summary"), dict) else {}
        turns = parsed.get("assistant_turns", [])
        if not isinstance(turns, list):
            turns = []

        # session summary row
        session_rows.append({
            "user_id": user_id,
            "session_id": session_id,
            "custom_id": cid,
            "file_path": file_path,
            "status_code": rec.get("status_code"),
            "parse_error": rec.get("parse_error"),
            "num_assistant_turns": st.get("num_assistant_turns", len(turns)),
            "num_score2": st.get("num_score2"),
            "num_score1_or_2": st.get("num_score1_or_2"),
            "rate_unprompted_agenda_advancing": st.get("rate_unprompted_agenda_advancing"),
            "notes": st.get("notes"),
            "model": rec.get("model"),
            "system_fingerprint": rec.get("system_fingerprint"),
        })

        # turn rows
        for t in turns:
            if not isinstance(t, dict):
                continue
            turn_rows.append({
                "user_id": user_id,
                "session_id": session_id,
                "custom_id": cid,
                "assistant_turn_index": t.get("assistant_turn_index"),
                "score": t.get("score"),
                "is_unprompted_agenda_advancing": t.get("is_unprompted_agenda_advancing"),
                "agenda_move_type": t.get("agenda_move_type"),
                "user_prompted": (t.get("evidence", {}) or {}).get("user_prompted") if isinstance(t.get("evidence"), dict) else None,
                "turn_notes": (t.get("evidence", {}) or {}).get("notes") if isinstance(t.get("evidence"), dict) else None,
            })

    sessions_df = pd.DataFrame(session_rows).sort_values(by=["user_id", "session_id"])
    turns_df = pd.DataFrame(turn_rows).sort_values(by=["user_id", "session_id", "assistant_turn_index"])
    return sessions_df, turns_df


# -------------------------
# Main
# -------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", default="../user_data", help="Root user_data directory")
    ap.add_argument("--out_dir", default="../out_proactivity_eval", help="Output directory")
    ap.add_argument("--model", default="gpt-5.2-pro", help="Model id (default: gpt-5.2-pro)")
    ap.add_argument("--prompt_file", default="", help="Optional: system prompt override file")
    ap.add_argument("--reasoning_effort", default="high", choices=["none", "low", "medium", "high", "xhigh"],
                    help="Reasoning effort (temperature is NOT used).")
    ap.add_argument("--poll_s", type=int, default=15, help="Batch polling interval (seconds)")
    ap.add_argument("--user_filter", default="", help="Optional: only evaluate users whose folder name contains this substring")
    args = ap.parse_args()

    user_data_dir = Path(args.user_data_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    safe_mkdir(out_dir)

    system_prompt = DEFAULT_PROACTIVITY_SYSTEM_PROMPT
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
        metadata={"job": "proactivity-eval", "model": args.model},
    )
    batch_id = batch.id
    print(f"  Batch created: batch_id={batch_id}")

    print("[4/6] Polling until batch completes ...")
    batch_final = poll_batch_until_done(client, batch_id, poll_s=args.poll_s)
    print(f"  Final status: {batch_final.status}")

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

    # Write results.jsonl (enriched session-level objects)
    idx_map = {r["custom_id"]: r for r in request_index}
    results_jsonl = out_dir / "results.jsonl"
    with results_jsonl.open("w", encoding="utf-8") as f:
        for rec in records:
            meta = idx_map.get(rec["custom_id"], {})
            out = {**meta, **rec}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"  Saved: {results_jsonl}")

    # Write readable JSON
    write_readable_outputs(out_dir, request_index, records)
    print(f"  Saved readable JSON -> {out_dir / 'readable'}")

    # Flatten to two Excel files: turns & sessions
    sessions_df, turns_df = flatten_session_and_turns(request_index, records)

    sessions_xlsx = out_dir / "results_sessions.xlsx"
    sessions_df.to_excel(sessions_xlsx, index=False)
    print(f"  Saved: {sessions_xlsx}")

    turns_xlsx = out_dir / "results_turns.xlsx"
    turns_df.to_excel(turns_xlsx, index=False)
    print(f"  Saved: {turns_xlsx}")

    print("\nDone.")
    print(f"Batch id: {batch_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
