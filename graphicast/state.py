"""JSON state file persistence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def _default() -> dict:
    return {"version": 1, "last_slot": None, "offices": {}}


def load_state(path: Path) -> dict:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _default()
    if not text.strip():
        return _default()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("state file %s is invalid JSON (%s); starting fresh", path, exc)
        return _default()
    if not isinstance(data, dict):
        log.warning("state file %s is not an object; starting fresh", path)
        return _default()
    return data


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
