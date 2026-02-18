#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eval_smart_topics.py

Batch-evaluate GLOBAL (multi-session) SMART goal quality per user, per domain (activity/sleep/nutrition),
extracting up to TWO distinct user-committed GOAL topics per domain across the full 5-session trajectory.

Reads (per user):
  ./user_data/<user_id>/chats/chat_all.json
If chat_all.json is missing, falls back to concatenating chat1.json ... chatN.json (chat_index.json ignored).

Writes (to --out_dir):
  batch_input.jsonl
  request_index.json
  batch_output.jsonl
  batch_error.jsonl (if any)
  results.jsonl                 (one row per user; includes parsed judge output + parse errors)
  results_goals.xlsx            (one row per user-domain-goal_slot)
  readable/
    combined_readable.json
    per_item/<custom_id>.json

Notes:
- Uses /v1/responses via Batch API.
- Does NOT use temperature (unsupported with reasoning models in your prior runs). See pattern in eval_smart_new.py.  
- Avoids .get() on Batch objects (pydantic): uses attributes. See eval_smart_new.py.  
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
# SMART judge prompt (GLOBAL multi-session, per-domain, up to 2 goals)
# -------------------------

DEFAULT_SMART_SYSTEM_PROMPT = r"""
You are an evaluation judge for a multi-session behavioral-health coaching dialogue system.

Input:
ONE user's multi-session transcript in JSON (multiple sessions).

Task:
For each domain (activity, sleep, nutrition), identify the last distinct user-committed GOAL topics across the full trajectory,
then score each goal using SMART (S, M, A, R=Reward, T=Timeframe) on strict 0–5 anchored rubrics.

GOAL definition (topic-level; what to extract):
- A GOAL is a concrete topic/object/event/behavior that the user explicitly commits to pursue in the domain.
  Examples: evening yoga routine; 20-minute pre-bed classical music; drink 2L water daily.
- Do NOT treat assistant-only suggestions as goals unless the user clearly accepts/commits.
- Do NOT treat constraints/preferences (e.g., too tired after dinner; dislike phone reminders) as goals.
  They are context for A (Achievable) and R (Reward).

Goal selection (per domain):
- current_goal: the latest user-committed goal topic in this domain.
- secondary_goal: another distinct user-committed goal topic in this domain (different topic/object/event), if present; else NONE.
- If there are more than two, keep the two most recent distinct goal topics.

Domains:
- activity: physical activity, exercise, movement, steps, workouts
- sleep: sleep schedule, duration, bedtime/wake time, sleep hygiene, wind-down routine
- nutrition: diet, meals, hydration, calories, food routines

SMART scoring (0–5 each; strict; evidence-based; no inference)
If goal_text = NONE, all five scores MUST be 0.

S = Specific (what exactly is done)
0: NONE
1: vague intention only
2: goal topic exists but action is ambiguous
3: clear action/topic but missing key execution qualifiers (e.g., when/where/trigger)
4: clear action/topic + at least one execution qualifier; minor ambiguity
5: executable without follow-up: action/topic + clear conditions (when/where/trigger) + basic frequency/condition

M = Measurable (how success is quantified)
0: NONE
1: no measurable criteria
2: weak non-quantitative terms (more/less/try) without a metric
3: at least one explicit quantifiable element (dose OR frequency OR duration OR logging), but incomplete
4: includes BOTH dose/duration/amount AND frequency/schedule (or clear verification), minor gaps
5: fully measurable and checkable: dose/duration/amount + frequency/schedule clearly stated (and/or explicit logging)

A = Achievable (feasibility given constraints mentioned in the transcript)
0: NONE
1: clearly infeasible or conflicts with stated constraints
2: feasibility unclear; no evidence it fits the user's situation
3: plausibly feasible but not explicitly adapted to key constraints/preferences
4: explicitly fits at least one stated constraint/preference (time, injury, workload, motivation, modality)
5: fits constraints AND includes calibrated difficulty or a low-friction backup plan that reduces failure risk

R = Reward (motivating reward contingent on completing the goal)
0: NONE or no reward concept present
1: reward vaguely implied but not specified
2: reward specified but weak/clarity contingency (maybe treat myself) or not tied to completion
3: reward is specified and tied to completion, but details are partial (timing/criteria unclear)
4: reward is clear, contingent, and feasible; minor gaps
5: reward is explicit, contingent on measurable completion, and well-integrated with the plan (clear trigger and timing)

T = Timeframe (deadline or schedule for when the behavior will occur)
0: NONE
1: no timeframe information
2: vague timing only (soon, later, sometime)
3: has a start point or coarse window (starting tomorrow, next week) but missing schedule/frequency
4: explicit schedule/frequency/time window exists; minor gaps in duration/assessment point
5: start point + explicit schedule/frequency + duration or evaluation point (for one week, then review)

Output:
Return VALID JSON only (no markdown, no extra text). Use EXACT schema:

{
  "domains": {
    "activity": {
      "current_goal": {
        "goal_text": "NONE or one concise user-facing goal topic",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "reward": 0, "timeframe": 0}
      },
      "secondary_goal": {
        "goal_text": "NONE or one concise user-facing goal topic",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "reward": 0, "timeframe": 0}
      }
    },
    "sleep": {
      "current_goal": {
        "goal_text": "NONE or one concise user-facing goal topic",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "reward": 0, "timeframe": 0}
      },
      "secondary_goal": {
        "goal_text": "NONE or one concise user-facing goal topic",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "reward": 0, "timeframe": 0}
      }
    },
    "nutrition": {
      "current_goal": {
        "goal_text": "NONE or one concise user-facing goal topic",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "reward": 0, "timeframe": 0}
      },
      "secondary_goal": {
        "goal_text": "NONE or one concise user-facing goal topic",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "reward": 0, "timeframe": 0}
      }
    }
  }
}

Important:
- Use only evidence in the transcript; do not infer missing details.
- Keep goal_text concise (one sentence fragment). No quotes in output.
"""


# -------------------------
# Utilities
# -------------------------

CHAT_FILE_RE = re.compile(r"^chat(\d+)\.json$", re.IGNORECASE)

def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))

def json_canonical_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)

def extract_output_text_from_responses_body(body: Dict[str, Any]) -> str:
    """Extract output text from a /v1/responses response body (best-effort)."""
    out_parts: List[str] = []
    output = body.get("output", [])
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
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
# Data discovery / building "chat_all"
# -------------------------

def discover_users(user_data_dir: Path) -> List[Path]:
    return [p for p in user_data_dir.iterdir() if p.is_dir()]

def discover_chat_all_for_user(user_dir: Path) -> Optional[Path]:
    p = user_dir / "chats" / "chat_all.json"
    return p if p.exists() and p.is_file() else None

def discover_session_chats_for_user(user_dir: Path) -> List[Tuple[int, Path]]:
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

def build_chat_all_json(user_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (chat_all_obj, meta)."""
    user_id = user_dir.name
    chat_all_path = discover_chat_all_for_user(user_dir)
    if chat_all_path:
        obj = load_json(chat_all_path)
        meta = {"source": "chat_all.json", "file_path": str(chat_all_path)}
        return obj, meta

    sessions = []
    src = []
    for sess_idx, p in discover_session_chats_for_user(user_dir):
        sess_obj = load_json(p)
        sessions.append({"session_id": sess_idx, "file": p.name, "payload": sess_obj})
        src.append(str(p))

    obj = {"user_id": user_id, "sessions": sessions}
    meta = {"source": "merged_chatN.json", "files": src}
    return obj, meta


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
    json_mode: bool = True,
) -> List[Dict[str, Any]]:
    users = discover_users(user_data_dir)
    if user_filter:
        users = [u for u in users if user_filter.lower() in u.name.lower()]

    request_index: List[Dict[str, Any]] = []

    with out_jsonl.open("w", encoding="utf-8") as f:
        for user_dir in users:
            user_id = user_dir.name
            chat_all_obj, meta = build_chat_all_json(user_dir)

            custom_id = user_id  # one request per user (per baseline)
            request_index.append({"custom_id": custom_id, "user_id": user_id, "source_meta": meta})

            user_payload = (
                "Now evaluate the following ONE user's multi-session transcript JSON.\n\n"
                "<CHAT_ALL_JSON>\n"
                f"{json_canonical_dumps(chat_all_obj)}\n"
                "</CHAT_ALL_JSON>\n"
            )

            body: Dict[str, Any] = {
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "reasoning": {"effort": reasoning_effort},
                "store": store,
            }

            if json_mode:
                body["text"] = {"format": {"type": "json_object"}}

            line = {"custom_id": custom_id, "method": "POST", "url": "/v1/responses", "body": body}
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    request_index_path.write_text(json.dumps(request_index, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_index


# -------------------------
# Output parsing + flattening
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
        body = (resp.get("body") or {}) if isinstance(resp, dict) else {}

        output_text = ""
        parsed = None
        parse_error = None

        if err is None and status_code == 200 and isinstance(body, dict):
            output_text = extract_output_text_from_responses_body(body)
            try:
                parsed = json.loads(output_text)
            except Exception as e:
                parse_error = f"{type(e).__name__}: {e}"
        else:
            parse_error = f"request_error: {err} status_code={status_code}"

        records.append(
            {
                "custom_id": custom_id,
                "status_code": status_code,
                "error": err,
                "output_text": output_text,
                "parsed": parsed,
                "parse_error": parse_error,
                "model": (body.get("model") if isinstance(body, dict) else None),
                "system_fingerprint": (body.get("system_fingerprint") if isinstance(body, dict) else None),
            }
        )
    return records

def compute_overall(scores: Dict[str, Any]) -> float:
    keys = ["specific", "measurable", "achievable", "reward", "timeframe"]
    vals = []
    for k in keys:
        try:
            vals.append(float(scores.get(k, 0)))
        except Exception:
            vals.append(0.0)
    return sum(vals) / 5.0 if vals else 0.0

def flatten_goal_rows(request_index: List[Dict[str, Any]], records: List[Dict[str, Any]]) -> pd.DataFrame:
    idx_map = {r["custom_id"]: r for r in request_index}
    rows: List[Dict[str, Any]] = []

    for rec in records:
        meta = idx_map.get(rec["custom_id"], {})
        user_id = meta.get("user_id") or rec["custom_id"]
        parsed = rec.get("parsed") if isinstance(rec.get("parsed"), dict) else {}
        domains = (parsed.get("domains") if isinstance(parsed, dict) else {}) or {}

        for domain in ["activity", "sleep", "nutrition"]:
            d_obj = domains.get(domain) if isinstance(domains, dict) else None
            if not isinstance(d_obj, dict):
                for slot in ["current_goal", "secondary_goal"]:
                    rows.append(
                        {
                            "user_id": user_id,
                            "domain": domain,
                            "goal_slot": slot,
                            "goal_text": "NONE",
                            "specific": 0,
                            "measurable": 0,
                            "achievable": 0,
                            "reward": 0,
                            "timeframe": 0,
                            "overall": 0.0,
                            "parse_error": rec.get("parse_error"),
                        }
                    )
                continue

            for slot in ["current_goal", "secondary_goal"]:
                g = d_obj.get(slot, {}) if isinstance(d_obj.get(slot), dict) else {}
                goal_text = g.get("goal_text", "NONE")
                scores = g.get("scores", {}) if isinstance(g.get("scores"), dict) else {}

                rows.append(
                    {
                        "user_id": user_id,
                        "domain": domain,
                        "goal_slot": slot,
                        "goal_text": goal_text,
                        "specific": scores.get("specific", 0),
                        "measurable": scores.get("measurable", 0),
                        "achievable": scores.get("achievable", 0),
                        "reward": scores.get("reward", 0),
                        "timeframe": scores.get("timeframe", 0),
                        "overall": compute_overall(scores) if str(goal_text).upper() != "NONE" else 0.0,
                        "parse_error": rec.get("parse_error"),
                    }
                )

    return pd.DataFrame(rows).sort_values(by=["user_id", "domain", "goal_slot"])


def write_readable_outputs(out_dir: Path, request_index: List[Dict[str, Any]], records: List[Dict[str, Any]]) -> None:
    readable_dir = out_dir / "readable"
    per_item_dir = readable_dir / "per_item"
    safe_mkdir(per_item_dir)

    idx_map = {r["custom_id"]: r for r in request_index}
    combined = []

    for rec in records:
        meta = idx_map.get(rec["custom_id"], {})
        obj = {**meta, **rec}
        combined.append(obj)
        (per_item_dir / f"{rec['custom_id']}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    (readable_dir / "combined_readable.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------------
# Main
# -------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", default="./user_data", help="Root user_data directory")
    ap.add_argument("--out_dir", default="./out_smart_eval", help="Output directory")
    ap.add_argument("--model", default="gpt-5.2-pro", help="Model id (default: gpt-5.2-pro)")
    ap.add_argument("--prompt_file", default="", help="Optional: system prompt override file")
    ap.add_argument(
        "--reasoning_effort",
        default="high",
        choices=["none", "low", "medium", "high", "xhigh"],
        help="Reasoning effort (temperature is NOT used).",
    )
    ap.add_argument("--poll_s", type=int, default=15, help="Batch polling interval (seconds)")
    ap.add_argument("--user_filter", default="", help="Optional: only evaluate users whose folder name contains this substring")
    ap.add_argument("--json_mode", action="store_true", help="Use Responses JSON mode (recommended).")
    args = ap.parse_args()

    user_data_dir = Path(args.user_data_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    safe_mkdir(out_dir)

    system_prompt = DEFAULT_SMART_SYSTEM_PROMPT
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
        json_mode=bool(args.json_mode),
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
        metadata={"job": "smart-goal-topics-eval", "model": args.model},
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
        print("request_counts:", getattr(batch_final, "request_counts", None))
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

    idx_map = {r["custom_id"]: r for r in request_index}
    results_jsonl = out_dir / "results.jsonl"
    with results_jsonl.open("w", encoding="utf-8") as f:
        for rec in records:
            meta = idx_map.get(rec["custom_id"], {})
            out = {**meta, **rec}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"  Saved: {results_jsonl}")

    write_readable_outputs(out_dir, request_index, records)
    print(f"  Saved readable JSON -> {out_dir / 'readable'}")

    goals_df = flatten_goal_rows(request_index, records)
    xlsx_path = out_dir / "results_goals.xlsx"
    goals_df.to_excel(xlsx_path, index=False)
    print(f"  Saved: {xlsx_path}")

    print("\nDone.")
    print(f"Batch id: {batch_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
