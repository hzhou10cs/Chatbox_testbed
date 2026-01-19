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


DEFAULT_JUDGE_SYSTEM_PROMPT = r"""
You are an evaluation judge for a behavioral-health coaching dialogue system.

Task: Evaluate IN-SESSION longitudinal progression by measuring redundancy of the ASSISTANT’S actionable suggestions
within ONE session. Use only this session. Do not infer missing content.

Two-stage workflow (must follow):
Stage A — Extract & classify suggestions
1) Consider assistant turns only.
2) Extract "suggestion units": any actionable advice / plan / option / concrete next-step.
   Exclude pure acknowledgements unless they contain an actionable suggestion.
3) For each suggestion unit, assign one BCT-like category:
   - action_planning
   - problem_solving
   - self_monitoring
   - feedback_reward
   - education_instruction
   - motivational_support
   - other

Stage B — Redundancy judgment (within session)
A suggestion unit is REDUNDANT if it repeats a previously stated suggestion in the same session with no meaningful new,
decision-relevant content. Paraphrases or re-ordering count as redundant.

Mark NON-REDUNDANT if it adds at least one meaningful novelty:
- adds_constraint (new frequency/duration/timing/quantity/threshold)
- adds_personalization (adapts to newly stated user context/preferences/barriers)
- adds_new_option (genuinely new alternative action)
- adds_new_rationale (new justification that changes decision-making; not generic praise)
- clarifies_ambiguity (resolves ambiguity or makes plan measurably clearer)

Special case:
If it repeats prior content purely to follow up on an unfinished commitment, label is_redundant=false but set
redundancy_reason to "constructive revisit" and cite the prior unit.

Output:
Return VALID JSON only (no markdown, no extra text). Use the schema:

{
  "units": [
    {
      "sid": "S1",
      "turn_idx": 0,
      "bct_type": "action_planning|problem_solving|self_monitoring|feedback_reward|education_instruction|motivational_support|other",
      "normalized": "canonical one-line suggestion",
      "quote_current": "verbatim assistant span",
      "is_redundant": true,
      "redundant_of": ["S0"],
      "quote_prior": "verbatim earlier assistant span (empty if not redundant)",
      "newness": {
        "adds_constraint": false,
        "adds_personalization": false,
        "adds_new_option": false,
        "adds_new_rationale": false,
        "clarifies_ambiguity": false
      },
      "redundancy_reason": "one sentence, evidence-based",
      "uncertainty_flag": 0
    }
  ],
  "summary": {
    "total_suggestions": 0,
    "redundant_suggestions": 0,
    "redundancy_rate": 0.0,
    "notes": "brief notes / edge cases"
  }
}

If uncertain, set uncertainty_flag=1 and explain briefly in redundancy_reason.
""".strip()


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


# -------------------------
# Batch builder
# -------------------------
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

                session_text = read_json_as_canonical_text(chat_path)
                user_payload = (
                    "Now evaluate the following single-session transcript JSON.\n\n"
                    "<SESSION_JSON>\n"
                    f"{session_text}\n"
                    "</SESSION_JSON>"
                )

                # IMPORTANT: no temperature here.
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
        summary = {}

        if err is None and status_code == 200 and isinstance(body, dict):
            output_text = extract_output_text_from_responses_body(body)
            try:
                parsed = json.loads(output_text)
                summary = (parsed.get("summary") if isinstance(parsed, dict) else {}) or {}
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
                "total_suggestions": summary.get("total_suggestions"),
                "redundant_suggestions": summary.get("redundant_suggestions"),
                "redundancy_rate": summary.get("redundancy_rate"),
                "notes": summary.get("notes"),
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

    system_prompt = DEFAULT_JUDGE_SYSTEM_PROMPT
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
        metadata={"job": "in-session-redundancy-eval", "model": args.model},
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
                "session_id": r.get("session_id"),
                "custom_id": r.get("custom_id"),
                "status_code": r.get("status_code"),
                "parse_error": r.get("parse_error"),
                "total_suggestions": r.get("total_suggestions"),
                "redundant_suggestions": r.get("redundant_suggestions"),
                "redundancy_rate": r.get("redundancy_rate"),
                "notes": r.get("notes"),
                "file_path": r.get("file_path"),
                "model": r.get("model"),
                "system_fingerprint": r.get("system_fingerprint"),
            }
            for r in enriched
        ]
    ).sort_values(by=["user_id", "session_id"])

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
