#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
summarize_repetitive_bct.py

Read repetitive eval outputs (results.jsonl) and produce BCT counts / redundant counts summaries.

Expected input:
  <out_repetitive_eval>/results.jsonl

Writes:
  <out_repetitive_eval>/bct_redundancy_summary.xlsx

Sheets:
  - unit_level (optional audit)
  - user_session_bct
  - user_bct_total
  - all_users_bct
  - overall_totals
  - session_totals
  - errors
"""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def safe_int(x) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out_dir", default="../out_repetitive_eval", help="Directory containing results.jsonl")
    ap.add_argument("--results_jsonl", default="", help="Optional explicit path to results.jsonl")
    ap.add_argument("--out_xlsx", default="", help="Optional explicit output xlsx path")
    ap.add_argument("--include_unit_level", action="store_true", help="Include unit_level sheet (can be large)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    results_path = Path(args.results_jsonl).expanduser().resolve() if args.results_jsonl else (out_dir / "results.jsonl")
    if not results_path.exists():
        raise FileNotFoundError(f"results.jsonl not found: {results_path}")

    out_xlsx = Path(args.out_xlsx).expanduser().resolve() if args.out_xlsx else (out_dir / "bct_redundancy_summary.xlsx")

    records = load_jsonl(results_path)

    unit_rows: List[Dict[str, Any]] = []
    session_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []

    for r in records:
        custom_id = r.get("custom_id")
        user_id = r.get("user_id")
        session_id = safe_int(r.get("session_id"))
        status_code = r.get("status_code")
        parse_error = r.get("parse_error")

        parsed = r.get("parsed")
        if not isinstance(parsed, dict):
            # record error/skip
            error_rows.append({
                "custom_id": custom_id,
                "user_id": user_id,
                "session_id": session_id,
                "status_code": status_code,
                "parse_error": parse_error or "missing_parsed",
            })
            continue

        units = parsed.get("units", [])
        summary = parsed.get("summary", {}) if isinstance(parsed.get("summary"), dict) else {}

        # session-level totals (prefer summary if present; fallback to units length)
        total_suggestions = summary.get("total_suggestions")
        redundant_suggestions = summary.get("redundant_suggestions")
        redundancy_rate = summary.get("redundancy_rate")

        if total_suggestions is None:
            total_suggestions = len(units) if isinstance(units, list) else None
        if redundant_suggestions is None and isinstance(units, list):
            redundant_suggestions = sum(1 for u in units if bool(u.get("is_redundant")))
        if redundancy_rate is None and total_suggestions not in (None, 0) and redundant_suggestions is not None:
            redundancy_rate = float(redundant_suggestions) / float(total_suggestions)

        session_rows.append({
            "user_id": user_id,
            "session_id": session_id,
            "custom_id": custom_id,
            "status_code": status_code,
            "parse_error": parse_error,
            "total_suggestions": total_suggestions,
            "redundant_suggestions": redundant_suggestions,
            "redundancy_rate": redundancy_rate,
            "notes": summary.get("notes"),
            "file_path": r.get("file_path"),
        })

        if not isinstance(units, list):
            error_rows.append({
                "custom_id": custom_id,
                "user_id": user_id,
                "session_id": session_id,
                "status_code": status_code,
                "parse_error": "units_not_list",
            })
            continue

        for u in units:
            bct = u.get("bct_type") or "unknown"
            is_red = bool(u.get("is_redundant"))
            unit_rows.append({
                "user_id": user_id,
                "session_id": session_id,
                "custom_id": custom_id,
                "sid": u.get("sid"),
                "turn_idx": u.get("turn_idx"),
                "bct_type": bct,
                "is_redundant": int(is_red),
            })

    unit_df = pd.DataFrame(unit_rows)
    session_df = pd.DataFrame(session_rows)
    errors_df = pd.DataFrame(error_rows)

    # If nothing parsed successfully
    if unit_df.empty:
        # still write errors & session totals
        with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
            session_df.to_excel(writer, sheet_name="session_totals", index=False)
            errors_df.to_excel(writer, sheet_name="errors", index=False)
        print(f"Saved: {out_xlsx}")
        return 0

    # Ensure types / ordering
    if "session_id" in unit_df.columns:
        unit_df["session_id"] = pd.to_numeric(unit_df["session_id"], errors="coerce").astype("Int64")
    if "session_id" in session_df.columns:
        session_df["session_id"] = pd.to_numeric(session_df["session_id"], errors="coerce").astype("Int64")

    # 1) per user per session per BCT
    user_session_bct = (
        unit_df.groupby(["user_id", "session_id", "bct_type"], dropna=False)
        .agg(
            bct_count=("bct_type", "size"),
            redundant_count=("is_redundant", "sum"),
        )
        .reset_index()
    )
    user_session_bct["redundancy_rate"] = user_session_bct["redundant_count"] / user_session_bct["bct_count"]

    # 2) per user across period per BCT
    user_bct_total = (
        unit_df.groupby(["user_id", "bct_type"], dropna=False)
        .agg(
            bct_count=("bct_type", "size"),
            redundant_count=("is_redundant", "sum"),
        )
        .reset_index()
    )
    user_bct_total["redundancy_rate"] = user_bct_total["redundant_count"] / user_bct_total["bct_count"]

    # 3) all users per BCT
    all_users_bct = (
        unit_df.groupby(["bct_type"], dropna=False)
        .agg(
            bct_count=("bct_type", "size"),
            redundant_count=("is_redundant", "sum"),
        )
        .reset_index()
        .sort_values(by=["bct_count"], ascending=False)
    )
    all_users_bct["redundancy_rate"] = all_users_bct["redundant_count"] / all_users_bct["bct_count"]

    # 4) overall totals
    overall_totals = pd.DataFrame([{
        "bct_total_count": int(unit_df.shape[0]),
        "bct_total_redundant": int(unit_df["is_redundant"].sum()),
        "overall_redundancy_rate": float(unit_df["is_redundant"].sum()) / float(unit_df.shape[0]) if unit_df.shape[0] else None,
        "num_users": int(unit_df["user_id"].nunique()),
        "num_sessions": int(unit_df[["user_id", "session_id"]].drop_duplicates().shape[0]),
    }])

    # Also include session totals (for quick sanity checks)
    session_totals = (
        unit_df.groupby(["user_id", "session_id"], dropna=False)
        .agg(
            total_suggestions=("bct_type", "size"),
            redundant_suggestions=("is_redundant", "sum"),
        )
        .reset_index()
    )
    session_totals["redundancy_rate"] = session_totals["redundant_suggestions"] / session_totals["total_suggestions"]

    # Write Excel
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        if args.include_unit_level:
            unit_df.sort_values(by=["user_id", "session_id", "turn_idx", "sid"]).to_excel(
                writer, sheet_name="unit_level", index=False
            )
        user_session_bct.sort_values(by=["user_id", "session_id", "bct_type"]).to_excel(
            writer, sheet_name="user_session_bct", index=False
        )
        user_bct_total.sort_values(by=["user_id", "bct_type"]).to_excel(
            writer, sheet_name="user_bct_total", index=False
        )
        all_users_bct.to_excel(writer, sheet_name="all_users_bct", index=False)
        overall_totals.to_excel(writer, sheet_name="overall_totals", index=False)
        session_totals.sort_values(by=["user_id", "session_id"]).to_excel(
            writer, sheet_name="session_totals", index=False
        )
        if not session_df.empty:
            session_df.sort_values(by=["user_id", "session_id"]).to_excel(
                writer, sheet_name="session_summary_from_judge", index=False
            )
        if not errors_df.empty:
            errors_df.to_excel(writer, sheet_name="errors", index=False)

    print(f"Saved: {out_xlsx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
