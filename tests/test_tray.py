"""Agent 单实例、IPC 与控制器（不创建真实图标/窗口）。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from weblauncher import paths, tray
from weblauncher.context import Runtime
from weblauncher.services.dsh import service
from weblauncher.services.dsh.settings import Settings


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def paths_(data_dir: Path) -> paths.Paths:
    return paths.Paths(data_dir)


def _runtime(tmp_path: Path, backend: object) -> Runtime:
    return Runtime.create(paths_=paths.Paths(tmp_path), backend=backend, migrate=False)


def _app(tmp_path: Path, backend: object | None = None) -> tray.TrayApp:
    runtime = _runtime(tmp_path, backend or SimpleNamespace())
    return tray.TrayApp(runtime, contexts=[runtime.context("dsh")])


def test_status_text_when_stopped(data_dir: Path) -> None:
    controller = service.Service(Settings())
    assert tray.status_text(controller) == "未运行"
    assert tray.state_text(controller) == "未运行"


def test_status_text_when_running(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = service.Service(Settings())
    state = service.State(pid=1234, create_time=1.0, port=18080)
    monkeypatch.setattr(controller, "read_state", lambda: state)
    monkeypatch.setattr(controller, "live_process", lambda value: SimpleNamespace(pid=1234))
    assert tray.status_text(controller) == "运行中 · pid=1234 · 127.0.0.1:18080"
    assert tray.state_text(controller) == "运行中"


def test_lock_is_single_instance(paths_: paths.Paths) -> None:
    first = tray.acquire_lock(paths_)
    assert first is not None
    try:
        assert tray.acquire_lock(paths_) is None
    finally:
        tray.release_lock(first)
    second = tray.acquire_lock(paths_)
    assert second is not None
    tray.release_lock(second)
    assert not paths_.tray_lock.exists()


def test_stale_lock_is_replaced(paths_: paths.Paths) -> None:
    path = paths_.tray_lock
    path.write_text(json.dumps({"pid": 999999999, "create_time": 1.0}), "utf-8")
    lock = tray.acquire_lock(paths_)
    assert lock is not None
    tray.release_lock(lock)
    assert not path.exists()


def test_fresh_unreadable_lock_is_respected(paths_: paths.Paths) -> None:
    paths_.tray_lock.write_text("", "utf-8")
    assert tray.acquire_lock(paths_) is None


def test_send_open_without_tray(paths_: paths.Paths) -> None:
    with pytest.raises(tray.TrayUnavailable):
        tray.send_open(paths_, 1.0)


def test_ipc_round_trip(paths_: paths.Paths) -> None:
    server = tray.IpcServer(lambda command: f"handled {command}", "token")
    server.start()
    tray._write_info(
        paths_,
        {
            "pid": os.getpid(),
            "create_time": psutil.Process().create_time(),
            "port": server.port,
            "token": "token",
        },
    )
    try:
        assert tray.running(paths_) == (os.getpid(), server.port)
        assert tray.send_open(paths_, 5.0) == "handled open"
    finally:
        server.close()
        tray._clear_info(paths_)
    assert tray.running(paths_) is None


def test_ipc_rejects_bad_token(data_dir: Path) -> None:
    server = tray.IpcServer(lambda command: "unreachable", "token")
    server.start()
    try:
        with pytest.raises(RuntimeError, match="unauthorized"):
            tray._request({"port": server.port, "token": "bad"}, "open", 5.0)
    finally:
        server.close()


def test_icon_image_loads_packaged_asset() -> None:
    image = tray.icon_image()
    assert image.size == (tray.ICON_SIZE, tray.ICON_SIZE)


def test_quit_stops_service_then_icon(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(data_dir)
    events: list[str] = []

    monkeypatch.setattr(app, "_batch", lambda action, **kwargs: events.append("service") or "ok")

    class FakeIcon:
        def stop(self) -> None:
            events.append("icon")

    app.icon = FakeIcon()
    app._stop_and_quit()
    assert events == ["service", "icon"]


def test_quit_still_stops_icon_when_service_stop_fails(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(data_dir)
    events: list[str] = []

    def boom(action: str, **kwargs: object) -> str:
        raise RuntimeError("boom")

    class FakeIcon:
        def stop(self) -> None:
            events.append("icon")

        def notify(self, message: str, title: str | None = None) -> None:
            events.append("notify")

    monkeypatch.setattr(app, "_batch", boom)
    app.icon = FakeIcon()
    app._stop_and_quit()
    assert events == ["notify", "icon"]
