#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eval_repetitive.py (updated)

Batch-evaluate IN-SESSION redundancy (assistant suggestion repetition) for multi-user session logs
using OpenAI Batch API (/v1/responses).

New supported layout:
  ../user_data
    /user_name1
      /chats
        chat1.json
        chat2.json
        ...
        chat5.json
        chat_index.json  (ignored)
    /user_name2
      ...

Outputs (example):
  ../out_repetitive_eval/
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

Notes:
- Avoids .get() on Batch objects (pydantic).
- Does NOT send temperature (gpt-5.2-pro rejects it with reasoning != none).
- Reads JSON with utf-8-sig to tolerate BOM on Windows.
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


REPETITION_JUDGE_SYSTEM_PROMPT = r"""
You are an evaluation judge for multi-session behavioral-health coaching dialogues.

Goal
Evaluate the efficiency of longitudinal progression by identifying redundant looping at the decision-making level.
You will (1) decompose each assistant turn into suggestion units and label each unit with a compact BCT category,
and (2) detect redundant loop events and loop segments across the full trajectory.

Input
ONE user's full multi-session transcript in JSON. It contains multiple sessions and turn-by-turn messages.

Key definitions

A. Suggestion unit
A suggestion unit is one atomic, actionable coaching move expressed by the assistant.
If one assistant message contains multiple actionable moves, split them into multiple units.

B. BCT category set (5)
Label each suggestion unit with exactly ONE category:
1) Planning: proposing or refining an action plan, schedule, or concrete steps (without primary focus on barriers, tracking, or rewards)
2) Barrier-solving: identifying, clarifying, or resolving obstacles or friction (motivation, time, environment, pain/injury, confusion)
3) Monitoring: tracking/logging, measurement criteria, check-ins, self-monitoring, metrics, or progress review mechanics
4) Reinforcement: explicit reward, reinforcement, celebration contingent on completion, incentives, commitment reward
5) Support/Guidance: general encouragement, empathy, education, generic advice, reflections that do not introduce a plan/barrier/monitor/reward decision

Fixed precedence (when a unit contains multiple elements)
Assign ONE label using this precedence order (first match wins):
Barrier-solving > Reinforcement > Monitoring > Planning > Support/Guidance
Rationale: barrier resolution, reinforcement, and monitoring are more decision-critical; Support/Guidance is fallback.

C. Decision unit (what can be looped)
A decision unit is the concrete decision point being progressed or revisited, such as:
- measurement/logging specifics (what metric, how often, threshold)
- timing/schedule (when, frequency, duration, start date)
- reward (what reward, contingency, trigger)
- tracking/monitoring method (tool, reminder, journal)
- barrier resolution step (specific obstacle and mitigation)
- plan choice/refinement (which activity, intensity, location, steps)
A suggestion unit can target one primary decision unit.

D. Redundant looping vs constructive revisiting
You will detect loops at the level of decision units across the full multi-session trajectory.

Redundant looping (failure mode):
The assistant revisits a previously addressed decision unit but does NOT add decision-relevant novelty.
No novelty means it does not add any of the following:
- new constraints that change feasibility (time window, injury constraint, environment constraint)
- a genuinely new option (not just rephrasing the same suggestion)
- measurable clarification (converting vague into quantifiable metric; specifying frequency/dose)
- a barrier-resolving step (specific obstacle -> specific mitigation step)
- a concrete commitment closure (user agrees and assistant finalizes next step)

Constructive revisiting (NOT a failure):
Returning to an earlier decision unit that:
- closes an unfinished commitment (confirms details or finalizes a previously open item)
- resolves a newly surfaced obstacle (new barrier appears and is handled)
- reduces execution friction with a practical next step (simplification, backup plan, implementation intention)

E. Loop event and loop segment
A redundant loop event is one assistant turn that qualifies as redundant looping.
A redundant loop segment is a contiguous span of turns consumed by the same redundant loop.
A segment has:
- start_turn_index (assistant turn index in the full trajectory)
- end_turn_index
- event_count (number of redundant loop events inside)
- cost_turns (number of assistant turns inside the segment that are redundant-looping turns)
Important: cost_turns counts assistant turns consumed by redundancy (not user turns).
Segments should merge adjacent redundant events if they pertain to the same decision unit and no novelty is introduced between them.

Task steps (do these in order)

1) Normalize the transcript into a single chronological list of turns across sessions.
2) Identify assistant turns only (ignore user turns for counting turns, but use user text as evidence for novelty/commitment).
3) For each assistant turn:
   a) Split into suggestion units.
   b) For each unit, assign:
      - bct_category (one of the 5)
      - decision_unit_target (one primary decision unit label, short string)
      - novelty_flag: "novel" or "non_novel" with respect to the prior trajectory for that same decision_unit_target
      - revisit_flag: whether this decision_unit_target has appeared before ("new" or "revisit")
      - loop_label:
         * "redundant_loop" if revisit + non_novel and not constructive
         * "constructive_revisit" if revisit but closes/advances in the constructive sense
         * "normal" otherwise
   c) A turn is a redundant loop event if ANY unit in that turn is labeled "redundant_loop".

4) Build redundant loop segments:
   - Group consecutive assistant turns that are redundant loop events targeting the same decision unit (or tightly same topic).
   - Each segment must have a short "segment_topic" and "dominant_bct" (the most frequent BCT among redundant units in that segment).

Output requirements
Return VALID JSON only. No markdown. No extra text.

Schema (EXACT):
{
  "meta": {
    "total_sessions": 0,
    "total_turns_all_roles": 0,
    "total_assistant_turns": 0
  },
  "turns": [
    {
      "assistant_turn_index": 0,
      "session_id": 0,
      "turn_id_in_session": 0,
      "assistant_text": "",
      "units": [
        {
          "unit_text": "",
          "bct": "Planning|Barrier-solving|Monitoring|Reinforcement|Support/Guidance",
          "decision_unit": "",
          "revisit": "new|revisit",
          "novelty": "novel|non_novel",
          "loop_label": "normal|redundant_loop|constructive_revisit"
        }
      ],
      "is_redundant_loop_event": false
    }
  ],
  "redundant_loop_segments": [
    {
      "segment_id": 0,
      "segment_topic": "",
      "decision_unit": "",
      "start_assistant_turn_index": 0,
      "end_assistant_turn_index": 0,
      "event_count": 0,
      "cost_turns": 0,
      "dominant_bct": "Planning|Barrier-solving|Monitoring|Reinforcement|Support/Guidance"
    }
  ],
  "summary": {
    "redundant_loop_events": 0,
    "loop_rate": 0.0,
    "loop_cost_turns": 0,
    "loop_cost_rate": 0.0,
    "average_loop_length": 0.0,
    "redundant_event_bct_counts": {
      "Planning": 0,
      "Barrier-solving": 0,
      "Monitoring": 0,
      "Reinforcement": 0,
      "Support/Guidance": 0
    }
  }
}

Computation rules (do NOT skip)
- total_assistant_turns counts assistant turns across all sessions.
- redundant_loop_events = number of turns where is_redundant_loop_event = true.
- loop_rate = redundant_loop_events / total_assistant_turns (0 if denominator is 0).
- loop_cost_turns = sum(cost_turns over redundant_loop_segments).
- loop_cost_rate = loop_cost_turns / total_assistant_turns (0 if denominator is 0).
- average_loop_length = loop_cost_turns / redundant_loop_events (0 if redundant_loop_events is 0).
- redundant_event_bct_counts: for each redundant loop event turn, count the BCT of each unit whose loop_label == "redundant_loop".
  (If multiple redundant units exist in one turn, count each of them.)

Constraints
- Be evidence-based: do not infer missing content.
- Do not label a revisit as redundant if it adds measurable clarification, new constraints, a new option, or resolves a barrier.
- Keep decision_unit strings short and consistent (e.g., "timeframe", "measurement", "tracking", "reward", "barrier_resolution", "plan_choice").
- If you are uncertain between redundant_loop and constructive_revisit, prefer constructive_revisit unless it is clearly a rephrase without advancement.
"""


# -------------------------
# Helpers
# -------------------------
CHAT_FILE_RE = re.compile(r"^chat(\d+)\.json$", re.IGNORECASE)


def safe_mkdir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> Any:
    # tolerate BOM on Windows
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def json_canonical_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


def read_json_as_canonical_text(path: Path) -> str:
    data = load_json(path)
    return json_canonical_dumps(data)


def extract_output_text_from_responses_body(body: Dict[str, Any]) -> str:
    # Some SDKs provide output_text; batch raw body may not.
    if isinstance(body, dict) and "output_text" in body and isinstance(body["output_text"], str):
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


def poll_batch_until_done(client: OpenAI, batch_id: str, poll_s: int = 15):
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
    if hasattr(resp, "text") and resp.text is not None:
        out_path.write_text(resp.text, encoding="utf-8")
        return
    data = getattr(resp, "content", None)
    if data is None:
        data = str(resp).encode("utf-8")
    out_path.write_bytes(data)


# -------------------------
# Data discovery (user_data layout)
# -------------------------
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





def build_batch_input_jsonl_from_user_data(
    user_data_dir: Path,
    out_jsonl: Path,
    request_index_path: Path,
    model: str,
    system_prompt: str,
    reasoning_effort: str = "high",
    store: bool = False,
    user_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Build ONE request per user, evaluating repetition/looping over the full multi-session trajectory.

    The judge expects ONE user's multi-session transcript JSON. We read it from:
      ./user_data/<user_id>/chats/chat_all.json
      {"user_id": <id>, "sessions": [{"session_id": i, "file": "...", "payload": <original session json>}, ...]}
    """
    users = discover_users(user_data_dir)
    if user_filter:
        users = [u for u in users if user_filter.lower() in u.name.lower()]

    request_index: List[Dict[str, Any]] = []
    lines_written = 0

    with out_jsonl.open("w", encoding="utf-8") as f:
        for user_dir in users:
            user_id = user_dir.name
            chats = discover_chats_for_user(user_dir)
            chat_all_path = user_dir / "chats" / "chat_all.json"
            if not chat_all_path.exists():
                # Skip users without pre-built multi-session file.
                continue

            custom_id = f"{user_id}"
            meta = {
                "custom_id": custom_id,
                "user_id": user_id,
                "num_sessions": 0,  # filled after loading chat_all.json
                "file_paths": [str(p) for _, p in chats],
            }
            request_index.append(meta)

            multi_obj = load_json(chat_all_path)
            # Fill metadata from chat_all.json if possible.
            try:
                sess = multi_obj.get("sessions", []) if isinstance(multi_obj, dict) else []
                meta["num_sessions"] = int(len(sess))
            except Exception:
                meta["num_sessions"] = meta.get("num_sessions", 0)

            multi_text = json_canonical_dumps(multi_obj)

            user_payload = (
                "Now evaluate the following MULTI-SESSION transcript JSON for one user.\n\n"
                "<CHAT_ALL_JSON>\n"
                f"{multi_text}\n"
                "</CHAT_ALL_JSON>"
            )

            # IMPORTANT: no temperature here (gpt-5.2-pro rejects it).
            body = {
                "model": model,
                "input": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "store": store,
                "reasoning": {"effort": reasoning_effort},
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
# Output parsing + readable JSON
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

        # extracted summary fields
        total_assistant_turns = None
        redundant_loop_events = None
        loop_rate = None
        loop_cost_turns = None
        loop_cost_rate = None
        average_loop_length = None
        bct_counts: Dict[str, Any] = {}

        if err is None and status_code == 200 and isinstance(body, dict):
            output_text = extract_output_text_from_responses_body(body)
            try:
                parsed = json.loads(output_text)
                if isinstance(parsed, dict):
                    meta = parsed.get("meta") or {}
                    summ = parsed.get("summary") or {}
                    total_assistant_turns = meta.get("total_assistant_turns")
                    redundant_loop_events = summ.get("redundant_loop_events")
                    loop_rate = summ.get("loop_rate")
                    loop_cost_turns = summ.get("loop_cost_turns")
                    loop_cost_rate = summ.get("loop_cost_rate")
                    average_loop_length = summ.get("average_loop_length")
                    bct_counts = (summ.get("redundant_event_bct_counts") or {}) if isinstance(summ, dict) else {}
            except Exception as e:
                parse_error = f"{type(e).__name__}: {e}"
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
                "total_assistant_turns": total_assistant_turns,
                "redundant_loop_events": redundant_loop_events,
                "loop_rate": loop_rate,
                "loop_cost_turns": loop_cost_turns,
                "loop_cost_rate": loop_cost_rate,
                "average_loop_length": average_loop_length,
                "bct_Planning": bct_counts.get("Planning"),
                "bct_Barrier-solving": bct_counts.get("Barrier-solving"),
                "bct_Monitoring": bct_counts.get("Monitoring"),
                "bct_Reinforcement": bct_counts.get("Reinforcement"),
                "bct_Support/Guidance": bct_counts.get("Support/Guidance"),
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

        user_id = meta.get("user_id", cid or "UNKNOWN_USER")
        combined[user_id] = item

    (readable_dir / "combined_readable.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )




# -------------------------
# Main
# -------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", default="../user_data", help="Root user_data directory")
    ap.add_argument("--out_dir", default="../out_repetitive_eval", help="Directory to write outputs")
    ap.add_argument("--model", default="gpt-5.2-pro", help="Model id (default: gpt-5.2-pro)")
    ap.add_argument("--prompt_file", default="", help="Optional: path to a system prompt text file")
    ap.add_argument(
        "--reasoning_effort",
        default="high",
        choices=["none", "low", "medium", "high", "xhigh"],
        help="Reasoning effort for GPT-5.* reasoning models (temperature is NOT used).",
    )
    ap.add_argument("--poll_s", type=int, default=15, help="Polling interval seconds")
    ap.add_argument("--user_filter", default="", help="Optional: only evaluate users whose folder name contains this substring")
    args = ap.parse_args()

    user_data_dir = Path(args.user_data_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    safe_mkdir(out_dir)

    system_prompt = REPETITION_JUDGE_SYSTEM_PROMPT
    if args.prompt_file:
        system_prompt = read_text(Path(args.prompt_file).expanduser().resolve()).strip()

    batch_input_jsonl = out_dir / "batch_input.jsonl"
    request_index_path = out_dir / "request_index.json"

    print(f"[1/6] Building batch input jsonl -> {batch_input_jsonl}")
    request_index = build_batch_input_jsonl_from_user_data(
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
        metadata={"job": "repetition-loop-eval", "model": args.model},
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
        print("No output_file_id available. Likely 0 successful requests.")
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

    # Map custom_id -> meta
    idx_map = {r["custom_id"]: r for r in request_index}

    # Write results.jsonl (enriched with user/session info)
    results_jsonl = out_dir / "results.jsonl"
    enriched: List[Dict[str, Any]] = []
    with results_jsonl.open("w", encoding="utf-8") as f:
        for rec in records:
            meta = idx_map.get(rec["custom_id"], {})
            out = {**meta, **rec}
            enriched.append(out)
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"  Saved: {results_jsonl}")

    # Write results.xlsx
    df = pd.DataFrame(
        [
            {
                "user_id": r.get("user_id"),
                "custom_id": r.get("custom_id"),
                "status_code": r.get("status_code"),
                "parse_error": r.get("parse_error"),
                "num_sessions": r.get("num_sessions"),
                "total_assistant_turns": r.get("total_assistant_turns"),
                "redundant_loop_events": r.get("redundant_loop_events"),
                "loop_rate": r.get("loop_rate"),
                "loop_cost_turns": r.get("loop_cost_turns"),
                "loop_cost_rate": r.get("loop_cost_rate"),
                "average_loop_length": r.get("average_loop_length"),
                "bct_Planning": r.get("bct_Planning"),
                "bct_Barrier-solving": r.get("bct_Barrier-solving"),
                "bct_Monitoring": r.get("bct_Monitoring"),
                "bct_Reinforcement": r.get("bct_Reinforcement"),
                "bct_Support/Guidance": r.get("bct_Support/Guidance"),
                "file_paths": json.dumps(r.get("file_paths", []), ensure_ascii=False),
                "model": r.get("model"),
                "system_fingerprint": r.get("system_fingerprint"),
            }
            for r in enriched
        ]
    ).sort_values(by=["user_id"])

    xlsx_path = out_dir / "results.xlsx"
    df.to_excel(xlsx_path, index=False)
    print(f"  Saved: {xlsx_path}")

    # Readable JSON outputs
    write_readable_outputs(out_dir, request_index, records)
    print(f"  Saved readable JSON -> {out_dir / 'readable'}")

    print("\nDone.")
    print(f"Batch id: {batch_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())