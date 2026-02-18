#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eval_proactivity.py (session-level)

Batch-evaluate session-level PROACTIVITY for multi-user, multi-session coaching logs.

Design (aligned with paper):
- Proactivity is session-level agenda management quality (ordinal 0-2).
- Record four event indicators per session:
  Timely Closure, Focus Transition, Barrier Handling, Deepening Move.

Reads (per user):
  ../user_data/<user_id>/chats/chat_all.json

Writes (in out_dir):
  batch_input.jsonl
  request_index.json
  batch_output.jsonl
  batch_error.jsonl (if any)
  results.jsonl                 (one row per session; includes parsed judge output)
  results_sessions.xlsx         (one row per session; key fields for analysis)
  results_users.xlsx            (per-user aggregates: mean score, event rates, trend slope)
  readable/
    combined_readable.json
    per_item/<custom_id>.json

Notes
- Uses /v1/responses via Batch API.
- Avoids unsupported parameters (e.g., temperature for gpt-5.2-pro with reasoning != none).
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from openai import OpenAI


# -------------------------
# Proactivity judge prompt
# -------------------------
DEFAULT_PROACTIVITY_SYSTEM_PROMPT = r"""
You are an evaluation judge for a multi-session behavioral-health coaching dialogue system.

Task
Given ONE full session transcript in JSON, evaluate SESSION-LEVEL proactivity.

Definition
Proactivity in longitudinal coaching is the agent’s ability to manage the session agenda through timely,
state-aware coaching moves, rather than merely responding to the user’s latest utterance.

A proactive session typically shows some combination of:
(1) Timely Closure: closes the session at an appropriate moment with a coherent wrap-up and a clear follow-up anchor.
(2) Focus Transition: transitions focus when the current topic has reached a stable plan or when the user declines further discussion.
(3) Barrier Handling: proactively identifies emerging barriers or ambivalence and initiates friction-reducing problem solving.
(4) Deepening Move: detects underspecified or uncertain goal elements and guides the dialogue toward actionable specificity.

Scoring (ordinal 0/1/2; session-level)
0 = largely reactive. Minimal agenda shaping; tends to stall, re-ask without progress, or lacks appropriate closure/transition.
1 = moderate agenda management. Shows some proactive moves, but timing or follow-through is inconsistent.
2 = strong agenda management. Sustained, well-timed proactive guidance, including appropriate closure or transitions.

Event indicators (0/1; per session)
Set each indicator to 1 if the move type occurs at least once in the session; else 0.
- timely_closure: assistant wraps up appropriately and anchors a next step or follow-up.
- focus_transition: assistant initiates a topic/domain/goal transition because current focus is stable or user declines.
- barrier_handling: assistant identifies or responds to barriers with a concrete friction-reducing step (not generic encouragement).
- deepening_move: assistant turns vague/underspecified goals into more specific/measurable/timeframed commitments.

Important constraints
- Be evidence-based. Do not infer missing content.
- Do NOT score based on "unprompted" alone; score agenda management quality and timing.
- If the session contains no meaningful planning context, score conservatively (likely 0 or 1 depending on agenda leadership).

Output requirements
Return VALID JSON only. No markdown. No extra text.

Use EXACT schema:
{
  "session_eval": {
    "proactivity_score": 0,
    "event_indicators": {
      "timely_closure": 0,
      "focus_transition": 0,
      "barrier_handling": 0,
      "deepening_move": 0
    },
    "assistant_turns": 0,
    "notes": ""
  }
}

Notes
- assistant_turns counts assistant messages only within this session.
- notes should be short (<= 25 words) and may be empty.
""".strip()


# -------------------------
# Helpers
# -------------------------
def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")  # tolerate BOM
    return json.loads(raw)


def json_canonical_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def try_parse_json(text: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj, None
        return None, "parsed_json_not_object"
    except Exception as e:
        return None, f"json_parse_error: {e}"


def extract_output_text_from_responses_body(body: Dict[str, Any]) -> str:
    """
    /v1/responses returns a 'output' list with content parts, or may include output_text.
    This tries multiple common shapes.
    """
    # Newer shape: body["output_text"]
    if isinstance(body.get("output_text"), str) and body["output_text"].strip():
        return body["output_text"]

    out = body.get("output")
    if isinstance(out, list):
        texts: List[str] = []
        for item in out:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                        texts.append(c["text"])
        if texts:
            return "\n".join(texts).strip()

    # Fallback: common older format
    if "choices" in body:
        try:
            return body["choices"][0]["message"]["content"]
        except Exception:
            pass

    return ""


def discover_users(user_data_dir: Path) -> List[Path]:
    if not user_data_dir.exists():
        return []
    return sorted([p for p in user_data_dir.iterdir() if p.is_dir()])


def load_chat_all_sessions(chat_all_path: Path) -> List[Dict[str, Any]]:
    """
    Accepts multiple possible chat_all.json formats.
    Returns a list of session dicts with at least a numeric 'session_id' field.
    """
    obj = load_json(chat_all_path)

    sessions: List[Any] = []
    if isinstance(obj, dict) and isinstance(obj.get("sessions"), list):
        sessions = obj["sessions"]
    elif isinstance(obj, list):
        sessions = obj
    else:
        # Unknown; best-effort wrap
        sessions = [obj]

    norm: List[Dict[str, Any]] = []
    for idx, s in enumerate(sessions, start=1):
        if isinstance(s, dict):
            sid = s.get("session_id")
            if sid is None:
                sid = s.get("id")
            if sid is None:
                sid = idx
            try:
                sid_int = int(sid)
            except Exception:
                sid_int = idx
            s2 = dict(s)
            s2["session_id"] = sid_int
            norm.append(s2)
        else:
            norm.append({"session_id": idx, "payload": s})
    # sort by session_id
    norm.sort(key=lambda x: x.get("session_id", 0))
    return norm


# -------------------------
# Batch IO
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
    with out_jsonl.open("w", encoding="utf-8") as f:
        for user_dir in users:
            user_id = user_dir.name
            chat_all_path = user_dir / "chats" / "chat_all.json"
            if not chat_all_path.exists():
                continue

            sessions = load_chat_all_sessions(chat_all_path)
            if not sessions:
                continue

            for sess in sessions:
                sess_id = int(sess.get("session_id", 0) or 0)
                custom_id = f"{user_id}__s{sess_id}"
                meta = {
                    "custom_id": custom_id,
                    "user_id": user_id,
                    "session_id": sess_id,
                    "chat_all_path": str(chat_all_path),
                }
                request_index.append(meta)

                user_payload = (
                    "Evaluate session-level proactivity and event indicators for this session.\n\n"
                    "<SESSION_JSON>\n"
                    f"{json_canonical_dumps(sess)}\n"
                    "</SESSION_JSON>\n"
                )

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

    request_index_path.write_text(json.dumps(request_index, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_index


def poll_batch_until_complete(client: OpenAI, batch_id: str, poll_interval: float = 5.0) -> Any:
    while True:
        b = client.batches.retrieve(batch_id)
        status = getattr(b, "status", None)
        print(f"[batch] {batch_id} status={status}")
        if status in ("completed", "failed", "cancelled", "expired"):
            return b
        time.sleep(poll_interval)


def download_file_content(client: OpenAI, file_id: str, out_path: Path) -> None:
    resp = client.files.content(file_id)
    # SDK may return a binary stream-like object
    if hasattr(resp, "write_to_file"):
        resp.write_to_file(out_path)
        return
    if hasattr(resp, "text") and isinstance(resp.text, str):
        out_path.write_text(resp.text, encoding="utf-8")
        return
    data = getattr(resp, "content", None)
    if data is None:
        data = str(resp).encode("utf-8")
    out_path.write_bytes(data)


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
                "output_text": output_text,
                "parsed": parsed,
                "parse_error": parse_error,
                "model": body.get("model"),
                "system_fingerprint": body.get("system_fingerprint"),
                "raw_body": body,
            }
        )
    return records


def write_readable_outputs(records: List[Dict[str, Any]], out_readable_dir: Path) -> None:
    safe_mkdir(out_readable_dir / "per_item")
    combined = []
    for r in records:
        cid = r.get("custom_id")
        item = {
            "custom_id": cid,
            "status_code": r.get("status_code"),
            "parse_error": r.get("parse_error"),
            "output_text": r.get("output_text"),
            "parsed": r.get("parsed"),
        }
        combined.append(item)
        (out_readable_dir / "per_item" / f"{cid}.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (out_readable_dir / "combined_readable.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_results_tables(
    records: List[Dict[str, Any]],
    request_index: List[Dict[str, Any]],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx_map = {r["custom_id"]: r for r in request_index}
    session_rows: List[Dict[str, Any]] = []
    jsonl_rows: List[Dict[str, Any]] = []

    for rec in records:
        cid = rec.get("custom_id")
        meta = idx_map.get(cid, {})
        user_id = meta.get("user_id")
        session_id = meta.get("session_id")
        chat_all_path = meta.get("chat_all_path")

        parsed = rec.get("parsed")
        if not isinstance(parsed, dict):
            row = {
                "user_id": user_id,
                "session_id": session_id,
                "custom_id": cid,
                "chat_all_path": chat_all_path,
                "status_code": rec.get("status_code"),
                "parse_error": rec.get("parse_error"),
                "proactivity_score": None,
                "timely_closure": None,
                "focus_transition": None,
                "barrier_handling": None,
                "deepening_move": None,
                "assistant_turns": None,
                "notes": None,
                "model": rec.get("model"),
                "system_fingerprint": rec.get("system_fingerprint"),
            }
            session_rows.append(row)
            jsonl_rows.append({**row, "parsed": None})
            continue

        se = parsed.get("session_eval", {}) if isinstance(parsed.get("session_eval"), dict) else {}
        ev = se.get("event_indicators", {}) if isinstance(se.get("event_indicators"), dict) else {}

        row = {
            "user_id": user_id,
            "session_id": session_id,
            "custom_id": cid,
            "chat_all_path": chat_all_path,
            "status_code": rec.get("status_code"),
            "parse_error": rec.get("parse_error"),
            "proactivity_score": se.get("proactivity_score"),
            "timely_closure": ev.get("timely_closure"),
            "focus_transition": ev.get("focus_transition"),
            "barrier_handling": ev.get("barrier_handling"),
            "deepening_move": ev.get("deepening_move"),
            "assistant_turns": se.get("assistant_turns"),
            "notes": se.get("notes"),
            "model": rec.get("model"),
            "system_fingerprint": rec.get("system_fingerprint"),
        }
        session_rows.append(row)
        jsonl_rows.append({**row, "parsed": parsed})

    df_sessions = pd.DataFrame(session_rows)
    df_jsonl = pd.DataFrame(jsonl_rows)

    # Per-user aggregates
    user_rows: List[Dict[str, Any]] = []
    for user_id, g in df_sessions.groupby("user_id", dropna=False):
        g_valid = g.dropna(subset=["proactivity_score"]).copy()
        # If session_id missing, treat as sequential
        if "session_id" in g_valid.columns:
            xs = g_valid["session_id"].astype(float).to_numpy() if len(g_valid) else np.array([])
        else:
            xs = np.arange(1, len(g_valid) + 1, dtype=float)

        ys = g_valid["proactivity_score"].astype(float).to_numpy() if len(g_valid) else np.array([])

        slope = None
        if len(xs) >= 2 and np.all(np.isfinite(xs)) and np.all(np.isfinite(ys)):
            try:
                slope = float(np.polyfit(xs, ys, 1)[0])
            except Exception:
                slope = None

        # event rates as mean over available sessions (ignore NaNs)
        def mean01(col: str) -> Optional[float]:
            if col not in g.columns:
                return None
            v = pd.to_numeric(g[col], errors="coerce")
            if v.notna().any():
                return float(v.mean())
            return None

        user_rows.append(
            {
                "user_id": user_id,
                "sessions_scored": int(g_valid.shape[0]),
                "mean_proactivity_score": float(pd.to_numeric(g["proactivity_score"], errors="coerce").mean())
                if pd.to_numeric(g["proactivity_score"], errors="coerce").notna().any()
                else None,
                "score_slope_over_sessions": slope,
                "timely_closure_rate": mean01("timely_closure"),
                "focus_transition_rate": mean01("focus_transition"),
                "barrier_handling_rate": mean01("barrier_handling"),
                "deepening_move_rate": mean01("deepening_move"),
                "total_assistant_turns": float(pd.to_numeric(g["assistant_turns"], errors="coerce").sum())
                if pd.to_numeric(g["assistant_turns"], errors="coerce").notna().any()
                else None,
            }
        )

    df_users = pd.DataFrame(user_rows)
    return df_sessions, df_users, df_jsonl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", type=str, default="./user_data")
    ap.add_argument("--out_dir", type=str, default="./out_proactivity_eval")
    ap.add_argument("--model", type=str, default="gpt-5.2-pro")
    ap.add_argument("--reasoning_effort", type=str, default="high", choices=["none", "low", "medium", "high"])
    ap.add_argument("--store", action="store_true")
    ap.add_argument("--user_filter", type=str, default=None)
    ap.add_argument("--prompt_path", type=str, default=None, help="Optional path to a system prompt text file.")
    args = ap.parse_args()

    user_data_dir = Path(args.user_data_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    safe_mkdir(out_dir)
    safe_mkdir(out_dir / "readable")

    system_prompt = DEFAULT_PROACTIVITY_SYSTEM_PROMPT
    if args.prompt_path:
        system_prompt = Path(args.prompt_path).read_text(encoding="utf-8")

    batch_input_path = out_dir / "batch_input.jsonl"
    request_index_path = out_dir / "request_index.json"

    request_index = build_batch_input_jsonl(
        user_data_dir=user_data_dir,
        out_jsonl=batch_input_path,
        request_index_path=request_index_path,
        model=args.model,
        system_prompt=system_prompt,
        reasoning_effort=args.reasoning_effort,
        store=args.store,
        user_filter=args.user_filter,
    )

    if not request_index:
        print("No requests prepared. Ensure chat_all.json exists under user_data/<user>/chats/.")
        return 1

    client = OpenAI()

    # Upload batch input
    print("[1/6] Uploading batch input file (purpose='batch') ...")
    up = client.files.create(file=batch_input_path.open("rb"), purpose="batch")
    input_file_id = getattr(up, "id", None)
    print(f"  Uploaded: file_id={input_file_id}")

    # Create batch
    print("[2/6] Creating batch (endpoint='/v1/responses', completion_window='24h') ...")
    batch = client.batches.create(
        input_file_id=input_file_id,
        endpoint="/v1/responses",
        completion_window="24h",
    )
    batch_id = getattr(batch, "id", None)
    print(f"  Batch created: batch_id={batch_id}")

    # Poll
    print("[3/6] Polling until batch completes ...")
    batch_final = poll_batch_until_complete(client, batch_id)

    status = getattr(batch_final, "status", None)
    print(f"  Final status: {status}")

    output_file_id = getattr(batch_final, "output_file_id", None)
    error_file_id = getattr(batch_final, "error_file_id", None)

    if not output_file_id:
        print("No output_file_id available. Batch may have failed validation. Check error file or dashboard.")
        if error_file_id:
            err_path = out_dir / "batch_error.jsonl"
            download_file_content(client, error_file_id, err_path)
            print(f"Downloaded error file to: {err_path}")
        return 2

    # Download outputs
    print("[4/6] Downloading batch output ...")
    batch_output_path = out_dir / "batch_output.jsonl"
    download_file_content(client, output_file_id, batch_output_path)
    print(f"  Saved: {batch_output_path}")

    if error_file_id:
        print("[5/6] Downloading batch error file ...")
        batch_error_path = out_dir / "batch_error.jsonl"
        download_file_content(client, error_file_id, batch_error_path)
        print(f"  Saved: {batch_error_path}")

    # Parse and write results
    print("[6/6] Parsing outputs and writing XLSX ...")
    records = parse_batch_output_jsonl(batch_output_path)
    write_readable_outputs(records, out_dir / "readable")

    df_sessions, df_users, df_jsonl = build_results_tables(records, request_index)

    # Write JSONL
    results_jsonl_path = out_dir / "results.jsonl"
    with results_jsonl_path.open("w", encoding="utf-8") as f:
        for _, r in df_jsonl.iterrows():
            f.write(json.dumps(r.dropna().to_dict(), ensure_ascii=False) + "\n")

    # Write XLSX
    sessions_xlsx = out_dir / "results_sessions.xlsx"
    users_xlsx = out_dir / "results_users.xlsx"
    df_sessions.to_excel(sessions_xlsx, index=False)
    df_users.to_excel(users_xlsx, index=False)

    print(f"Wrote: {sessions_xlsx}")
    print(f"Wrote: {users_xlsx}")
    print(f"Wrote: {results_jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
