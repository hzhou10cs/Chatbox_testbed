#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
build_chat_all.py

Combine per-user chat1.json ... chatN.json into a single multi-session file: chat_all.json
written to the same directory: ./user_data/<user_id>/chats/chat_all.json

Default expected layout:
  ./user_data/
    <user_id>/
      chats/
        chat1.json
        chat2.json
        ...
        chat5.json
        chat_index.json (ignored)

Output format (stable, matches eval_smart_topics.py fallback structure):
{
  "user_id": "<user_id>",
  "sessions": [
    {"session_id": 1, "file": "chat1.json", "payload": <original_json>},
    ...
  ]
}

Usage:
  python ./evaluation/build_chat_all.py --user_data_dir ./user_data
Options:
  --overwrite     overwrite existing chat_all.json
  --min_sessions  require at least this many chat*.json to write chat_all.json (default 1)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

CHAT_FILE_RE = re.compile(r"^chat(\d+)\.json$", re.IGNORECASE)

def load_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))

def safe_write_json(p: Path, obj: Any) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def discover_session_chats(chats_dir: Path) -> List[Tuple[int, Path]]:
    items: List[Tuple[int, Path]] = []
    for fp in chats_dir.iterdir():
        if not fp.is_file():
            continue
        if fp.name.lower() == "chat_index.json":
            continue
        if fp.name.lower() == "chat_all.json":
            continue
        m = CHAT_FILE_RE.match(fp.name)
        if m:
            items.append((int(m.group(1)), fp))
    items.sort(key=lambda x: x[0])
    return items

def build_for_user(user_dir: Path, overwrite: bool, min_sessions: int) -> Dict[str, Any]:
    user_id = user_dir.name
    chats_dir = user_dir / "chats"
    if not chats_dir.exists():
        return {"user_id": user_id, "status": "skip", "reason": "missing chats dir"}

    out_path = chats_dir / "chat_all.json"
    if out_path.exists() and not overwrite:
        return {"user_id": user_id, "status": "skip", "reason": "chat_all.json exists"}

    sess_files = discover_session_chats(chats_dir)
    if len(sess_files) < min_sessions:
        return {"user_id": user_id, "status": "skip", "reason": f"only {len(sess_files)} sessions (<{min_sessions})"}

    sessions = []
    for sess_idx, fp in sess_files:
        try:
            payload = load_json(fp)
        except Exception as e:
            return {"user_id": user_id, "status": "error", "reason": f"failed to read {fp.name}: {type(e).__name__}: {e}"}
        sessions.append({"session_id": sess_idx, "file": fp.name, "payload": payload})

    chat_all = {"user_id": user_id, "sessions": sessions}
    try:
        safe_write_json(out_path, chat_all)
    except Exception as e:
        return {"user_id": user_id, "status": "error", "reason": f"failed to write chat_all.json: {type(e).__name__}: {e}"}

    return {"user_id": user_id, "status": "ok", "sessions": len(sessions), "output": str(out_path)}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user_data_dir", default="./user_data", help="Root directory containing per-user folders")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing chat_all.json")
    ap.add_argument("--min_sessions", type=int, default=1, help="Minimum number of chat*.json required to write chat_all.json")
    args = ap.parse_args()

    root = Path(args.user_data_dir).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: user_data_dir not found: {root}")
        return 2

    users = [p for p in root.iterdir() if p.is_dir()]
    users.sort(key=lambda p: p.name.lower())

    summary = {"ok": 0, "skip": 0, "error": 0}
    details = []

    for user_dir in users:
        res = build_for_user(user_dir, overwrite=args.overwrite, min_sessions=args.min_sessions)
        details.append(res)
        summary[res["status"]] = summary.get(res["status"], 0) + 1
        msg = f"[{res['status']}] {res['user_id']}"
        if res["status"] == "ok":
            msg += f" sessions={res.get('sessions')} -> {res.get('output')}"
        else:
            msg += f" reason={res.get('reason')}"
        print(msg)

    # Write a small report next to root for audit (optional, harmless)
    report_path = root / "_chat_all_build_report.json"
    try:
        safe_write_json(report_path, {"summary": summary, "details": details})
        print(f"\nReport saved: {report_path}")
    except Exception:
        pass

    return 0 if summary.get("error", 0) == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
