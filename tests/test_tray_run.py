"""托盘入口的三条编排路径：投递已有托盘、成为托盘、兜底直接打开。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dshlauncher.context import Context
from dshlauncher.paths import Paths
from dshlauncher.settings import Settings
from dshlauncher.tray import app as tray_app
from dshlauncher.tray.ipc import TrayUnavailable


def _context(tmp_path: Path) -> Context:
    return Context.create(Settings(), paths_=Paths(tmp_path))


def test_run_delegates_to_existing_tray(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []

    def fake_send(paths_: Paths, timeout: float, *, wait: float = 0.0) -> str:
        calls.append(wait)
        return "opened"

    monkeypatch.setattr(tray_app, "send_open", fake_send)
    assert tray_app.run(Settings(), context=_context(tmp_path)) == 0
    assert calls == [0.0]


def test_run_becomes_tray_when_lock_acquired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(paths_: Paths, timeout: float, *, wait: float = 0.0) -> str:
        raise TrayUnavailable("none")

    lock = object()
    released: list[object] = []

    class FakeApp:
        def __init__(self, settings: Settings, *, context: Context) -> None:
            self.context = context

        def run(self) -> int:
            return 7

    monkeypatch.setattr(tray_app, "send_open", fake_send)
    monkeypatch.setattr(tray_app, "acquire_lock", lambda paths_: lock)
    monkeypatch.setattr(tray_app, "release_lock", lambda value: released.append(value))
    monkeypatch.setattr(tray_app, "TrayApp", FakeApp)

    assert tray_app.run(Settings(), context=_context(tmp_path)) == 7
    assert released == [lock]


def test_run_falls_back_to_direct_open_when_lock_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_send(paths_: Paths, timeout: float, *, wait: float = 0.0) -> str:
        raise TrayUnavailable("none")

    opened: list[Context] = []

    def fake_open(context: Context) -> str:
        opened.append(context)
        return "pid=1 started=True window=new"

    monkeypatch.setattr(tray_app, "send_open", fake_send)
    monkeypatch.setattr(tray_app, "acquire_lock", lambda paths_: None)
    monkeypatch.setattr(tray_app.actions, "open_dsh", fake_open)

    assert tray_app.run(Settings(), context=_context(tmp_path)) == 0
    assert len(opened) == 1
