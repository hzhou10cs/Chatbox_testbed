# coach_state_io.py
"""
Utility functions for loading and saving the per-user coaching STATE JSON.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict


def load_state(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: str | Path, obj: Dict[str, Any]) -> None:
    p = Path(path)
    parent = p.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix=".tmp_state_", dir=str(parent), text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(p))
