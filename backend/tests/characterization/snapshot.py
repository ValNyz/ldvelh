"""Approval-style JSON snapshots for characterization tests."""

import json
import os
from pathlib import Path

SNAP_DIR = Path(__file__).parent / "snapshots"


def assert_snapshot(name: str, data: dict) -> None:
    """Compare data with snapshots/<name>.json (UPDATE_SNAPSHOTS=1 rewrites it)."""
    path = SNAP_DIR / f"{name}.json"
    rendered = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if os.getenv("UPDATE_SNAPSHOTS") == "1" or not path.exists():
        existed = path.exists()
        path.write_text(rendered, encoding="utf-8")
        if not existed and os.getenv("UPDATE_SNAPSHOTS") != "1":
            raise AssertionError(f"New snapshot written: {path.name} — review it and re-run")
        return
    expected = path.read_text(encoding="utf-8")
    assert rendered == expected, f"Snapshot mismatch for {name}; diff {path} (UPDATE_SNAPSHOTS=1 to accept)"
