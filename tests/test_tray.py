"""托盘单实例、IPC 与状态文本（不创建真实图标/窗口）。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from dshlauncher import paths, service, tray
from dshlauncher.context import Context
from dshlauncher.settings import Settings


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def paths_(data_dir: Path) -> paths.Paths:
    return paths.Paths(data_dir)


def _context(paths_: paths.Paths, backend: object) -> Context:
    return replace(Context.create(Settings(), paths_=paths_), backend=backend)


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
    # 另一个实例刚创建锁文件、内容还没写完：不能抢。
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
    app = tray.TrayApp(Settings())
    events: list[str] = []

    def stop_service() -> bool:
        events.append("service")
        return True

    class FakeIcon:
        def stop(self) -> None:
            events.append("icon")

    monkeypatch.setattr(app.controller, "stop", stop_service)
    app.icon = FakeIcon()
    app._stop_and_quit()
    assert events == ["service", "icon"]


def test_quit_still_stops_icon_when_service_stop_fails(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tray.TrayApp(Settings())
    events: list[str] = []

    def stop_service() -> bool:
        raise RuntimeError("boom")

    class FakeIcon:
        def stop(self) -> None:
            events.append("icon")

        def notify(self, message: str, title: str | None = None) -> None:
            events.append("notify")

    monkeypatch.setattr(app.controller, "stop", stop_service)
    app.icon = FakeIcon()
    app._stop_and_quit()
    assert events == ["notify", "icon"]


def test_show_details_opens_dialog(paths_: paths.Paths, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    backend = SimpleNamespace(message=lambda title, text, **kwargs: calls.append((title, text)))
    context = _context(paths_, backend)
    app = tray.TrayApp(context.settings, context=context)
    monkeypatch.setattr(app.controller, "describe", lambda: "服务: 运行中\nPID : 1")
    app._details_lock.acquire()
    app._show_details()
    assert calls == [("DeepSeek Harness 服务状态", "服务: 运行中\nPID : 1")]
    assert app._details_lock.acquire(blocking=False)


def test_show_details_reports_describe_failure(paths_: paths.Paths, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    backend = SimpleNamespace(message=lambda title, text, **kwargs: calls.append((title, text)))
    context = _context(paths_, backend)
    app = tray.TrayApp(context.settings, context=context)

    def boom() -> str:
        raise RuntimeError("no state")

    monkeypatch.setattr(app.controller, "describe", boom)
    app._details_lock.acquire()
    app._show_details()
    assert calls and calls[0][1].startswith("读取状态失败")
    assert app._details_lock.acquire(blocking=False)


def test_show_details_notifies_when_dialog_fails(
    paths_: paths.Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    notified: list[str] = []

    def boom(title: str, text: str, **kwargs: object) -> None:
        raise RuntimeError("no dialog")

    context = _context(paths_, SimpleNamespace(message=boom))
    app = tray.TrayApp(context.settings, context=context)
    monkeypatch.setattr(app.controller, "describe", lambda: "服务: 未运行")
    monkeypatch.setattr(app, "_notify", lambda text: notified.append(text))
    app._details_lock.acquire()
    app._show_details()
    assert notified and "打开状态窗口失败" in notified[0]
    assert app._details_lock.acquire(blocking=False)


def test_schedule_refresh_coalesces(paths_: paths.Paths, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(paths_, SimpleNamespace())
    app = tray.TrayApp(context.settings, context=context)
    calls: list[bool] = []
    monkeypatch.setattr(app, "_refresh", lambda: calls.append(True))
    app._schedule_refresh()
    app._schedule_refresh()
    time.sleep(0.3)
    assert calls == [True]


def test_controller_reports_starting(paths_: paths.Paths) -> None:
    context = _context(paths_, SimpleNamespace())
    controller = tray.TrayController(context)
    controller._starting.set()
    assert controller.status_short() == "启动中"
    assert controller.status_tooltip() == "正在启动服务…"
    controller._starting.clear()
    assert controller.status_short() == "未运行"


def test_show_panel_reuses_server_and_releases_lock(
    paths_: paths.Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dshlauncher.tray import app as tray_app

    app = tray.TrayApp(Settings(), context=_context(paths_, SimpleNamespace()))
    created: list[object] = []

    class FakePanel:
        url = "http://127.0.0.1:1/token/"

        def __init__(self, context: object, *, exclusive: object = None) -> None:
            created.append(self)

        def start(self) -> None:
            pass

        def open_window(self) -> str:
            return "new"

    monkeypatch.setattr(tray_app.updates_panel, "PanelServer", FakePanel)
    app._panel_lock.acquire()
    app._show_panel()
    assert len(created) == 1
    assert app.panel is created[0]
    assert app._panel_lock.acquire(blocking=False)
    app._panel_lock.release()


def test_exclusive_rejects_busy_controller(paths_: paths.Paths) -> None:
    from dshlauncher.upgrade import BusyError

    app = tray.TrayApp(Settings(), context=_context(paths_, SimpleNamespace()))
    app.controller._busy.acquire()
    try:
        with pytest.raises(BusyError):
            app._exclusive(lambda: None)
    finally:
        app.controller._busy.release()


def test_exclusive_releases_controller_after_work(paths_: paths.Paths) -> None:
    app = tray.TrayApp(Settings(), context=_context(paths_, SimpleNamespace()))
    calls: list[str] = []
    app._exclusive(lambda: calls.append("work"))
    assert calls == ["work"]
    assert app.controller._busy.acquire(blocking=False)
    app.controller._busy.release()
