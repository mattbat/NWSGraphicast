from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphicast import state as state_mod
from graphicast.state import load_state, save_state

DEFAULT = {"version": 1, "last_slot": None, "offices": {}}


def test_missing_file(tmp_path: Path) -> None:
    assert load_state(tmp_path / "nope.json") == DEFAULT


def test_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("")
    assert load_state(p) == DEFAULT


def test_invalid_json(tmp_path: Path, caplog) -> None:
    p = tmp_path / "s.json"
    p.write_text("{not json")
    assert load_state(p) == DEFAULT
    assert "invalid JSON" in caplog.text


def test_non_object_json(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("[1, 2]")
    assert load_state(p) == DEFAULT


def test_default_not_shared(tmp_path: Path) -> None:
    a = load_state(tmp_path / "x")
    a["offices"]["oun"] = {}
    assert load_state(tmp_path / "x") == DEFAULT


def test_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "dir" / "s.json"
    data = {
        "version": 1,
        "last_slot": "2026-11-06T06:00:00-06:00",
        "offices": {"oun": {"fingerprint": "ab", "sent_at": "now"}},
    }
    save_state(p, data)
    assert load_state(p) == data
    text = p.read_text()
    assert text.endswith("\n") and "\n  " in text
    assert [f.name for f in p.parent.iterdir()] == ["s.json"]


def test_overwrite(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    save_state(p, {"a": 1})
    save_state(p, {"a": 2})
    assert json.loads(p.read_text()) == {"a": 2}


def test_failed_save_cleans_temp_and_keeps_old(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "s.json"
    save_state(p, {"a": 1})

    def boom(*_a, **_k):
        raise OSError("replace failed")

    monkeypatch.setattr(state_mod.os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        save_state(p, {"a": 2})
    assert json.loads(p.read_text()) == {"a": 1}
    assert [f.name for f in tmp_path.iterdir()] == ["s.json"]
