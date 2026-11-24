"""原子写：读者永远看不到半个文件。"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from weblauncher import paths


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


def test_legacy_brand_data_dir_is_renamed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEBLAUNCHER_HOME", raising=False)
    monkeypatch.setattr(paths, "executable_dir", lambda: tmp_path)
    old = tmp_path / ".dshlauncher"
    old.mkdir()
    (old / "marker").write_text("x", "utf-8")
    paths.data_dir.cache_clear()
    try:
        assert paths.data_dir() == tmp_path / ".weblauncher"
        assert (tmp_path / ".weblauncher" / "marker").read_text("utf-8") == "x"
        assert not old.exists()
    finally:
        paths.data_dir.cache_clear()


def test_legacy_user_fallback_migrates_into_writable_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install = tmp_path / "install"
    install.mkdir()
    user_root = tmp_path / "user"
    legacy = user_root / "dshlauncher"
    legacy.mkdir(parents=True)
    (legacy / "config.toml").write_text("x", "utf-8")
    monkeypatch.delenv("WEBLAUNCHER_HOME", raising=False)
    monkeypatch.setattr(paths, "executable_dir", lambda: install)
    monkeypatch.setattr(paths, "_user_data_dir", lambda name="weblauncher": user_root / name)
    paths.data_dir.cache_clear()
    try:
        assert paths.data_dir() == install / ".weblauncher"
        assert (install / ".weblauncher" / "config.toml").read_text("utf-8") == "x"
    finally:
        paths.data_dir.cache_clear()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_runtime_dirs_and_logs_are_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    bundle = paths.Paths(tmp_path)
    bundle.ensure()
    service = bundle.service("dsh")
    service.ensure()
    handle = paths.open_append(service.log)
    handle.close()
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(service.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(service.log.stat().st_mode) == 0o600
