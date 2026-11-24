"""Agent 入口：已有控制台就投递，否则成为常驻进程。"""

from __future__ import annotations

from pathlib import Path

import pytest

from weblauncher import paths
from weblauncher.context import Runtime
from weblauncher.tray import app as tray_app
from weblauncher.tray.ipc import TrayUnavailable


def _runtime(tmp_path: Path, backend: object | None = None) -> Runtime:
    return Runtime.create(paths_=paths.Paths(tmp_path), backend=backend, migrate=False)


def test_run_opens_existing_console(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[float, float, str]] = []
    opened: list[str] = []

    def fake_send(paths_, timeout: float, *, wait: float = 0.0, target: str = "/#/") -> str:
        sent.append((timeout, wait, target))
        return "http://127.0.0.1:1/boot/ticket"

    monkeypatch.setattr(tray_app, "send_ui", fake_send)
    monkeypatch.setattr(tray_app, "open_console_url", lambda runtime, url: opened.append(url) or "new")

    assert tray_app.run(_runtime(tmp_path), target="/#/updates") == 0
    assert sent[0][1] == 0.0
    assert sent[0][2] == "/#/updates"
    assert opened == ["http://127.0.0.1:1/boot/ticket"]


def test_run_becomes_agent_when_lock_acquired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(paths_, timeout: float, *, wait: float = 0.0, target: str = "/#/") -> str:
        raise TrayUnavailable("none")

    lock = object()
    released: list[object] = []

    class FakeApp:
        def __init__(self, runtime: Runtime, *, target: str = "/#/") -> None:
            self.runtime = runtime
            self.target = target

        def run(self) -> int:
            return 7

    monkeypatch.setattr(tray_app, "send_ui", fake_send)
    monkeypatch.setattr(tray_app, "acquire_lock", lambda paths_: lock)
    monkeypatch.setattr(tray_app, "release_lock", lambda value: released.append(value))
    monkeypatch.setattr(tray_app, "TrayApp", FakeApp)

    assert tray_app.run(_runtime(tmp_path)) == 7
    assert released == [lock]


def test_run_waits_for_starting_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []
    opened: list[str] = []

    def fake_send(paths_, timeout: float, *, wait: float = 0.0, target: str = "/#/") -> str:
        calls.append(wait)
        if not wait:
            raise TrayUnavailable("none")
        return "http://127.0.0.1:1/boot/ticket"

    monkeypatch.setattr(tray_app, "send_ui", fake_send)
    monkeypatch.setattr(tray_app, "open_console_url", lambda runtime, url: opened.append(url) or "new")
    monkeypatch.setattr(tray_app, "acquire_lock", lambda paths_: None)

    assert tray_app.run(_runtime(tmp_path)) == 0
    assert calls == [0.0, tray_app.START_WAIT]
    assert opened
