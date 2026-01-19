#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
eval_smart.py

Batch-evaluate SMART goal quality globally per session, per domain (activity/sleep/nutrition).
For each session, the judge extracts a representative goal per domain (or NONE) and scores S/M/A/R/T (0-5).

Reads:
  ../user_data/<user_id>/chats/chat1.json ... chatN.json (chat_index.json ignored)

Writes:
  ../out_smart_eval/
    batch_input.jsonl
    batch_output.jsonl
    batch_error.jsonl (if any)
    request_index.json
    results.jsonl
    results_sessions.xlsx     (one row per session)
    results_goals.xlsx        (one row per user-session-domain; missing domains filled as NONE/0)
    readable/
      combined_readable.json
      per_item/<custom_id>.json

Notes:
- Uses /v1/responses via Batch API.
- Avoids temperature (unsupported in gpt-5.2-pro with reasoning).
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
# SMART judge prompt (session-level, per-domain)
# -------------------------
DEFAULT_SMART_SYSTEM_PROMPT = r"""
You are an evaluation judge for a behavioral-health coaching dialogue system.

Task:
Given ONE full session transcript in JSON, extract a representative, user-facing goal for EACH domain
(activity, sleep, nutrition) if present in this session, and score its SMART quality.

Important constraints:
- Do NOT assume a goal exists. If the session does not contain an explicit or confirmed goal for a domain,
  output goal_text as "NONE" and set all scores to 0 for that domain.
- A domain goal may be refined across multiple turns. Within this session, summarize the overall goal of a domain at this session, 
  and evaluate based on the final summarized goal for each domain (not 'NONE') instead of extract goals from individual turns.
- Prefer goals that are user commitments/agreements. If only the assistant suggests something and the user does not
  accept/commit, treat as no goal for that domain.

Domains:
- activity: physical activity, exercise, movement, steps, workouts
- sleep: sleep schedule, duration, bedtime, wake time, sleep hygiene
- nutrition: diet, meals, calories, hydration, food choices

SMART scoring (0-5 each):
- Specific: clarity of what action/outcome is targeted
- Measurable: existence/clarity of measurable criteria (frequency/duration/amount/threshold/observable metric)
- Achievable: feasibility given context mentioned in THIS session (0 if no goal)
- Relevant: alignment with user's stated needs/priorities in THIS session (0 if no goal)
- TimeBound: presence/clarity of time frame, deadline, or duration (e.g., "next week", "for 2 weeks", "by date")

Scoring anchors:
0 = not present / not applicable (use 0 when goal_text is NONE)
1-2 = weak/partial; major ambiguity or missing key details
3 = moderate; core intent clear but some missing/uncertain details
4 = strong; mostly complete, minor gaps
5 = fully complete and unambiguous for the dimension

Output requirements:
- Output VALID JSON only. No markdown, no extra text.
- Use EXACT schema:

{
  "domains": {
    "activity": {
      "goal_text": "NONE or a single concise goal statement",
      "evidence": {"supporting_quotes": [], "notes": ""},
      "scores": {"specific": 0, "measurable": 0, "achievable": 0, "relevant": 0, "time_bound": 0},
      "overall": 0.0
    },
    "sleep": { ... same schema ... },
    "nutrition": { ... same schema ... }
  },
  "session_summary": {
    "num_domains_with_goals": 0,
    "overall_mean_across_present_domains": 0.0,
    "notes": ""
  }
}

Rules:
- overall = mean of the five scores for that domain (0 if goal_text is NONE).
- num_domains_with_goals counts domains where goal_text != "NONE".
- overall_mean_across_present_domains is the mean of domain overall among domains with goals; 0.0 if none present.
- supporting_quotes: include up to 2 short quotes (<=25 words each) from the transcript that justify the extracted goal.
""".strip()


# -------------------------
# Helpers
# -------------------------
CHAT_FILE_RE = re.compile(r"^chat(\d+)\.json$", re.IGNORECASE)
DOMAINS = ["activity", "sleep", "nutrition"]


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
                    "Extract per-domain representative goals (activity/sleep/nutrition) from this single session JSON "
                    "and score SMART (0-5 each dimension). If absent, use NONE and zeros.\n\n"
                    "<SESSION_JSON>\n"
                    f"{json_canonical_dumps(session_json)}\n"
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


# -------------------------
# Flatten to tables
# -------------------------
def normalize_domain_output(dom_out: Any) -> Dict[str, Any]:
    """
    Ensure each domain has goal_text, scores, overall.
    Missing/invalid -> NONE/0.
    """
    base = {
        "goal_text": "NONE",
        "scores": {"specific": 0, "measurable": 0, "achievable": 0, "relevant": 0, "time_bound": 0},
        "overall": 0.0,
        "evidence": {"supporting_quotes": [], "notes": ""},
    }
    if not isinstance(dom_out, dict):
        return base

    goal_text = dom_out.get("goal_text")
    if not isinstance(goal_text, str) or not goal_text.strip():
        goal_text = "NONE"
    goal_text = goal_text.strip()

    scores = dom_out.get("scores")
    if not isinstance(scores, dict):
        scores = {}
    def sget(k: str) -> int:
        v = scores.get(k, 0)
        try:
            iv = int(v)
        except Exception:
            iv = 0
        return max(0, min(5, iv))

    sc = {
        "specific": sget("specific"),
        "measurable": sget("measurable"),
        "achievable": sget("achievable"),
        "relevant": sget("relevant"),
        "time_bound": sget("time_bound"),
    }

    # overall: if judge provided valid, keep; else compute
    ov = dom_out.get("overall")
    try:
        ovf = float(ov)
    except Exception:
        ovf = sum(sc.values()) / 5.0 if goal_text.upper() != "NONE" else 0.0

    # enforce NONE rule: if NONE then zeros
    if goal_text.upper() == "NONE":
        sc = {k: 0 for k in sc}
        ovf = 0.0

    ev = dom_out.get("evidence")
    if not isinstance(ev, dict):
        ev = {"supporting_quotes": [], "notes": ""}
    if "supporting_quotes" not in ev or not isinstance(ev.get("supporting_quotes"), list):
        ev["supporting_quotes"] = []
    if "notes" not in ev or not isinstance(ev.get("notes"), str):
        ev["notes"] = ""

    return {"goal_text": goal_text, "scores": sc, "overall": ovf, "evidence": ev}


def flatten_records(request_index: List[Dict[str, Any]], records: List[Dict[str, Any]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    sessions_df: one row per session
    goals_df: one row per user-session-domain (missing domains filled with NONE/0)
    """
    idx_map = {r["custom_id"]: r for r in request_index}

    session_rows: List[Dict[str, Any]] = []
    goal_rows: List[Dict[str, Any]] = []

    for rec in records:
        cid = rec["custom_id"]
        meta = idx_map.get(cid, {})
        user_id = meta.get("user_id")
        session_id = meta.get("session_id")
        file_path = meta.get("file_path")

        parsed = rec.get("parsed")
        if not isinstance(parsed, dict):
            # still write empty domain rows with parse_error for alignment
            session_rows.append({
                "user_id": user_id,
                "session_id": session_id,
                "custom_id": cid,
                "file_path": file_path,
                "status_code": rec.get("status_code"),
                "parse_error": rec.get("parse_error"),
                "num_domains_with_goals": None,
                "overall_mean_across_present_domains": None,
                "notes": None,
                "model": rec.get("model"),
                "system_fingerprint": rec.get("system_fingerprint"),
            })
            for d in DOMAINS:
                goal_rows.append({
                    "user_id": user_id,
                    "session_id": session_id,
                    "custom_id": cid,
                    "domain": d,
                    "goal_present": 0,
                    "goal_text": "NONE",
                    "specific": 0,
                    "measurable": 0,
                    "achievable": 0,
                    "relevant": 0,
                    "time_bound": 0,
                    "domain_overall": 0.0,
                    "supporting_quotes": "",
                    "domain_notes": "",
                    "parse_error": rec.get("parse_error"),
                })
            continue

        doms = parsed.get("domains", {})
        if not isinstance(doms, dict):
            doms = {}

        normed = {d: normalize_domain_output(doms.get(d)) for d in DOMAINS}

        # session summary
        ss = parsed.get("session_summary", {})
        if not isinstance(ss, dict):
            ss = {}

        # Compute fallback summary if missing
        num_domains_with_goals = ss.get("num_domains_with_goals")
        if num_domains_with_goals is None:
            num_domains_with_goals = sum(1 for d in DOMAINS if normed[d]["goal_text"].upper() != "NONE")

        overall_mean = ss.get("overall_mean_across_present_domains")
        try:
            overall_mean = float(overall_mean)
        except Exception:
            present = [normed[d]["overall"] for d in DOMAINS if normed[d]["goal_text"].upper() != "NONE"]
            overall_mean = sum(present) / len(present) if present else 0.0

        session_rows.append({
            "user_id": user_id,
            "session_id": session_id,
            "custom_id": cid,
            "file_path": file_path,
            "status_code": rec.get("status_code"),
            "parse_error": rec.get("parse_error"),
            "num_domains_with_goals": int(num_domains_with_goals),
            "overall_mean_across_present_domains": overall_mean,
            "notes": ss.get("notes"),
            "model": rec.get("model"),
            "system_fingerprint": rec.get("system_fingerprint"),
        })

        # goal rows
        for d in DOMAINS:
            item = normed[d]
            sc = item["scores"]
            goal_present = 0 if item["goal_text"].upper() == "NONE" else 1
            quotes = item["evidence"].get("supporting_quotes", [])
            goal_rows.append({
                "user_id": user_id,
                "session_id": session_id,
                "custom_id": cid,
                "domain": d,
                "goal_present": goal_present,
                "goal_text": item["goal_text"],
                "specific": sc["specific"],
                "measurable": sc["measurable"],
                "achievable": sc["achievable"],
                "relevant": sc["relevant"],
                "time_bound": sc["time_bound"],
                "domain_overall": float(item["overall"]),
                "supporting_quotes": " | ".join([str(q) for q in quotes[:2]]),
                "domain_notes": item["evidence"].get("notes", ""),
                "parse_error": rec.get("parse_error"),
            })

    sessions_df = pd.DataFrame(session_rows).sort_values(by=["user_id", "session_id"])
    goals_df = pd.DataFrame(goal_rows).sort_values(by=["user_id", "session_id", "domain"])
    return sessions_df, goals_df


# -------------------------
# Main
# -------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", default="../user_data", help="Root user_data directory")
    ap.add_argument("--out_dir", default="../out_smart_eval", help="Output directory")
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
        metadata={"job": "smart-goal-eval", "model": args.model},
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

    # Readable JSON
    write_readable_outputs(out_dir, request_index, records)
    print(f"  Saved readable JSON -> {out_dir / 'readable'}")

    # Flatten and write Excel
    sessions_df, goals_df = flatten_records(request_index, records)

    sessions_xlsx = out_dir / "results_sessions.xlsx"
    sessions_df.to_excel(sessions_xlsx, index=False)
    print(f"  Saved: {sessions_xlsx}")

    goals_xlsx = out_dir / "results_goals.xlsx"
    goals_df.to_excel(goals_xlsx, index=False)
    print(f"  Saved: {goals_xlsx}")

    print("\nDone.")
    print(f"Batch id: {batch_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
