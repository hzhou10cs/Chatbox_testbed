#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Convert OpenAI Batch API output jsonl (for /v1/responses) into readable JSON files.

Inputs:
  - batch_output.jsonl (each line: {custom_id, response:{status_code, body:{...}}})

Outputs (in out_dir):
  - combined_readable.json         # {custom_id: {judge: <parsed>, meta: {...}}}
  - index_summary.json             # list of per-custom_id summaries
  - per_item/<custom_id>.json      # one file per request
  - parse_failures.json            # only items whose judge JSON could not be parsed

Usage:
  python convert_batch_output.py --in /path/to/batch_output.jsonl --out /path/to/out_dir
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def extract_output_text(body: Dict[str, Any]) -> str:
    """Best-effort extraction of assistant output text from a Responses API body."""
    if not isinstance(body, dict):
        return ""

    # Newer responses sometimes include output_text directly
    if isinstance(body.get("output_text"), str):
        return body["output_text"]

    out = body.get("output")
    if isinstance(out, list):
        parts: List[str] = []
        for item in out:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message" and item.get("role") == "assistant":
                content = item.get("content")
                if isinstance(content, list):
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                            parts.append(c["text"])
        if parts:
            return "\n".join(parts)

    return ""


def safe_json_loads(s: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(s), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Path to batch_output.jsonl")
    ap.add_argument("--out", dest="out", required=True, help="Output directory")
    args = ap.parse_args()

    in_path = Path(args.inp).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    per_item_dir = out_dir / "per_item"
    per_item_dir.mkdir(parents=True, exist_ok=True)

    combined: Dict[str, Any] = {}
    index: List[Dict[str, Any]] = []
    failures: Dict[str, Any] = {}

    lines = in_path.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        obj = json.loads(line)
        custom_id = obj.get("custom_id")
        resp = (obj.get("response") or {})
        status_code = resp.get("status_code")
        body = (resp.get("body") or {})
        err = obj.get("error")

        output_text = ""
        judge_json = None
        parse_error = None

        if status_code == 200 and err is None and isinstance(body, dict):
            output_text = extract_output_text(body)
            judge_json, parse_error = safe_json_loads(output_text) if output_text else (None, "empty_output_text")
        else:
            parse_error = f"request_failed status_code={status_code} error={err}"

        meta = {
            "line_no": line_no,
            "status_code": status_code,
            "request_id": resp.get("request_id"),
            "model": body.get("model") if isinstance(body, dict) else None,
            "created_at": body.get("created_at") if isinstance(body, dict) else None,
            "completed_at": body.get("completed_at") if isinstance(body, dict) else None,
            "usage": body.get("usage") if isinstance(body, dict) else None,
            "parse_error": parse_error,
        }

        # Build a compact summary row
        summary = None
        if isinstance(judge_json, dict):
            summary = judge_json.get("summary")

        idx_row = {
            "custom_id": custom_id,
            "status_code": status_code,
            "parse_error": parse_error,
            "total_suggestions": (summary or {}).get("total_suggestions") if isinstance(summary, dict) else None,
            "redundant_suggestions": (summary or {}).get("redundant_suggestions") if isinstance(summary, dict) else None,
            "redundancy_rate": (summary or {}).get("redundancy_rate") if isinstance(summary, dict) else None,
            "model": meta["model"],
        }
        index.append(idx_row)

        item_obj = {
            "custom_id": custom_id,
            "judge": judge_json,
            "meta": meta,
            # keep the raw text for audit/debug; optional but useful
            "raw_output_text": output_text,
        }

        combined[str(custom_id)] = item_obj

        # Write per-item pretty JSON
        per_path = per_item_dir / f"{custom_id}.json"
        per_path.write_text(json.dumps(item_obj, ensure_ascii=False, indent=2), encoding="utf-8")

        if judge_json is None:
            failures[str(custom_id)] = item_obj

    (out_dir / "combined_readable.json").write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "index_summary.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures:
        (out_dir / "parse_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {len(combined)} items to {out_dir}")
    print(f"Per-item JSON: {per_item_dir}")
    if failures:
        print(f"Parse failures: {len(failures)} (see parse_failures.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
