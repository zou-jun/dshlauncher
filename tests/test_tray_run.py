"""托盘入口的三条编排路径：投递已有托盘、成为托盘、兜底直接打开。"""

from __future__ import annotations

from pathlib import Path

import pytest

from weblauncher import paths
from weblauncher.context import Runtime
from weblauncher.tray import app as tray_app
from weblauncher.tray.ipc import TrayUnavailable


def _runtime(tmp_path: Path, backend: object | None = None) -> Runtime:
    return Runtime.create(paths_=paths.Paths(tmp_path), backend=backend, migrate=False)


def test_run_delegates_to_existing_tray(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[float, float]] = []

    def fake_send(paths_, timeout: float, *, wait: float = 0.0) -> str:
        calls.append((timeout, wait))
        return "opened"

    monkeypatch.setattr(tray_app, "send_open", fake_send)
    assert tray_app.run(_runtime(tmp_path)) == 0
    assert calls[0][1] == 0.0
    assert calls[0][0] > 5.0


def test_run_becomes_tray_when_lock_acquired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(paths_, timeout: float, *, wait: float = 0.0) -> str:
        raise TrayUnavailable("none")

    lock = object()
    released: list[object] = []

    class FakeApp:
        def __init__(self, runtime: Runtime) -> None:
            self.runtime = runtime

        def run(self) -> int:
            return 7

    monkeypatch.setattr(tray_app, "send_open", fake_send)
    monkeypatch.setattr(tray_app, "acquire_lock", lambda paths_: lock)
    monkeypatch.setattr(tray_app, "release_lock", lambda value: released.append(value))
    monkeypatch.setattr(tray_app, "TrayApp", FakeApp)

    assert tray_app.run(_runtime(tmp_path)) == 7
    assert released == [lock]


def test_run_falls_back_to_direct_open_when_lock_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_send(paths_, timeout: float, *, wait: float = 0.0) -> str:
        raise TrayUnavailable("none")

    opened: list[str] = []

    class FakeApp:
        def __init__(self, runtime: Runtime) -> None:
            self.runtime = runtime

        def _open_defaults(self) -> str:
            opened.append("open")
            return "ok"

    monkeypatch.setattr(tray_app, "send_open", fake_send)
    monkeypatch.setattr(tray_app, "acquire_lock", lambda paths_: None)
    monkeypatch.setattr(tray_app, "TrayApp", FakeApp)

    assert tray_app.run(_runtime(tmp_path)) == 0
    assert opened == ["open"]
