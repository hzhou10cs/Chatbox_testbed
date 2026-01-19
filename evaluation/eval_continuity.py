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
DEFAULT_CONTINUITY_SYSTEM_PROMPT = r"""
You are an evaluation judge for a behavioral-health coaching dialogue system.

Task:
Given TWO consecutive sessions (Session 1 and Session 2), score whether Session 2 incorporates Session 1’s
commitments, barriers, and context, showing state-dependent adaptation rather than a generic restart.

Constraints:
- Use ONLY the provided JSON transcripts.
- Do NOT use CST or external memory.
- Do NOT infer unstated facts.
- Score Session 2 RELATIVE TO Session 1.

Scoring:
Use 0/1/2 ordinal scores per dimension:
0 = absent / generic restart
1 = partially present / inconsistent
2 = clearly present / strong continuity and adaptation

Dimensions (max 5):
1) reuse_of_prior: Session 2 reuses prior goals/plans/preferences from Session 1 (not starting from scratch).
2) followup_on_commitments_barriers: Session 2 follows up on unfinished commitments or barriers mentioned in Session 1.
3) context_alignment_opening: Session 2’s opening and early turns are aligned with Session 1 context (not generic).
4) agenda_progression: Session 2 progresses the agenda beyond Session 1 rather than repeating the same discussion.
5) smooth_handoff_no_reset: Session 2 shows smooth semantic handoff (no abrupt reset / unrelated generic reset).

Evidence policy (lightweight):
Provide a small list of turn indices as evidence where helpful, but keep notes short.

Output requirements:
- Output VALID JSON only. No markdown, no extra text.
- Use EXACT schema:

{
  "scores": {
    "reuse_of_prior": {"score": 0, "evidence_s2_turns": [0], "notes": ""},
    "followup_on_commitments_barriers": {"score": 0, "evidence_s2_turns": [0], "notes": ""},
    "context_alignment_opening": {"score": 0, "evidence_s2_turns": [0], "notes": ""},
    "agenda_progression": {"score": 0, "evidence_s2_turns": [0], "notes": ""},
    "smooth_handoff_no_reset": {"score": 0, "evidence_s2_turns": [0], "notes": ""}
  },
  "overall": {"score_0_to_10": 0, "notes": ""},
  "uncertainty_flag": 0
}

Notes:
- evidence_s2_turns refers to indices of turns in Session 2 (assistant+user sequence as given).
- If uncertain due to missing signals, set uncertainty_flag=1 and explain briefly in overall.notes.
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
CHAT_FILE_RE = re.compile(r"^chat(\d+)\.json$", re.IGNORECASE)


def discover_users(user_data_dir: Path) -> List[Path]:
    return [p for p in user_data_dir.iterdir() if p.is_dir()]


def discover_chats_for_user(user_dir: Path) -> List[Tuple[int, Path]]:
    chats_dir = user_dir / "chats"
    if not chats_dir.exists():
        return []
    pairs: List[Tuple[int, Path]] = []
    for p in chats_dir.iterdir():
        if not p.is_file():
            continue
        if p.name.lower() == "chat_index.json":
            continue
        m = CHAT_FILE_RE.match(p.name)
        if m:
            idx = int(m.group(1))
            pairs.append((idx, p))
    pairs.sort(key=lambda x: x[0])
    return pairs


def build_consecutive_pairs(chat_list: List[Tuple[int, Path]]) -> List[Tuple[int, Path, int, Path]]:
    """
    Given sorted chats [(1,path1),(2,path2),...], produce consecutive pairs:
    (i, path_i, j, path_j) for consecutive indices in list ordering.
    """
    out: List[Tuple[int, Path, int, Path]] = []
    for a, b in zip(chat_list, chat_list[1:]):
        out.append((a[0], a[1], b[0], b[1]))
    return out


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
            chats = discover_chats_for_user(user_dir)
            if len(chats) < 2:
                continue

            pairs = build_consecutive_pairs(chats)
            for s1_idx, s1_path, s2_idx, s2_path in pairs:
                custom_id = f"{user_id}__{s1_idx}-{s2_idx}"
                # Keep stable mapping for later lookup
                req_meta = {
                    "custom_id": custom_id,
                    "user_id": user_id,
                    "pair_id": f"{s1_idx}-{s2_idx}",
                    "session_prev": s1_idx,
                    "session_curr": s2_idx,
                    "file_prev": str(s1_path),
                    "file_curr": str(s2_path),
                }
                request_index.append(req_meta)

                s1_json = load_json(s1_path)
                s2_json = load_json(s2_path)

                user_payload = (
                    "Evaluate continuity between two consecutive sessions.\n\n"
                    "<SESSION_1_JSON>\n"
                    f"{json_canonical_dumps(s1_json)}\n"
                    "</SESSION_1_JSON>\n\n"
                    "<SESSION_2_JSON>\n"
                    f"{json_canonical_dumps(s2_json)}\n"
                    "</SESSION_2_JSON>\n"
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


def flatten_scores(parsed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        "reuse_of_prior": None,
        "followup_on_commitments_barriers": None,
        "context_alignment_opening": None,
        "agenda_progression": None,
        "smooth_handoff_no_reset": None,
        "overall_0_to_10": None,
        "overall_notes": None,
        "uncertainty_flag": None,
    }
    if not isinstance(parsed, dict):
        return out

    scores = parsed.get("scores", {})
    if isinstance(scores, dict):
        for k in [
            "reuse_of_prior",
            "followup_on_commitments_barriers",
            "context_alignment_opening",
            "agenda_progression",
            "smooth_handoff_no_reset",
        ]:
            v = scores.get(k, {})
            if isinstance(v, dict):
                out[k] = v.get("score")
    overall = parsed.get("overall", {})
    if isinstance(overall, dict):
        out["overall_0_to_10"] = overall.get("score_0_to_10")
        out["overall_notes"] = overall.get("notes")
    out["uncertainty_flag"] = parsed.get("uncertainty_flag")
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
        pair_id = meta.get("pair_id", "UNKNOWN_PAIR")
        combined.setdefault(user_id, {})
        combined[user_id][pair_id] = item

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

    system_prompt = DEFAULT_CONTINUITY_SYSTEM_PROMPT
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
            flat = flatten_scores(rec["parsed"])
            out = {**meta, **rec, **flat}
            enriched.append(out)
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"  Saved: {results_jsonl}")

    # Write results.xlsx (one row per pair)
    df = pd.DataFrame(
        [
            {
                "user_id": r.get("user_id"),
                "pair_id": r.get("pair_id"),
                "session_prev": r.get("session_prev"),
                "session_curr": r.get("session_curr"),
                "custom_id": r.get("custom_id"),
                "status_code": r.get("status_code"),
                "parse_error": r.get("parse_error"),
                "reuse_of_prior": r.get("reuse_of_prior"),
                "followup_on_commitments_barriers": r.get("followup_on_commitments_barriers"),
                "context_alignment_opening": r.get("context_alignment_opening"),
                "agenda_progression": r.get("agenda_progression"),
                "smooth_handoff_no_reset": r.get("smooth_handoff_no_reset"),
                "overall_0_to_10": r.get("overall_0_to_10"),
                "uncertainty_flag": r.get("uncertainty_flag"),
                "file_prev": r.get("file_prev"),
                "file_curr": r.get("file_curr"),
                "model": r.get("model"),
                "system_fingerprint": r.get("system_fingerprint"),
            }
            for r in enriched
        ]
    ).sort_values(by=["user_id", "session_prev", "session_curr"])

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
