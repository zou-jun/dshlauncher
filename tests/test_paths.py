"""原子写：读者永远看不到半个文件。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dshlauncher import paths


def test_write_atomic_replaces_and_cleans_temp(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    paths.write_atomic(target, '{"pid": 1}')
    assert json.loads(target.read_text("utf-8")) == {"pid": 1}

    paths.write_atomic(target, '{"pid": 2}')
    assert json.loads(target.read_text("utf-8")) == {"pid": 2}
    assert list(tmp_path.glob("state.json.*.tmp")) == []


def test_write_atomic_creates_parent(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "state.json"
    paths.write_atomic(target, "{}")
    assert target.read_text("utf-8") == "{}"


def test_audit_rotates_old_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "AUDIT_ROTATE_BYTES", 10)

    paths.audit("first")
    paths.audit("second")

    rotated = tmp_path / "launcher.log.1"
    assert "first" in rotated.read_text("utf-8")
    current = (tmp_path / "launcher.log").read_text("utf-8")
    assert "second" in current


def test_audit_collapses_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    paths.audit("boom", detail="Traceback\n  line one\n  line two")
    text = (tmp_path / "launcher.log").read_text("utf-8")
    assert "boom | Traceback | line one | line two" in text
