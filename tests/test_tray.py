"""托盘单实例、IPC 与状态文本（不创建真实图标/窗口）。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from dshlauncher import paths, service, tray
from dshlauncher.settings import Settings


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path


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


def test_lock_is_single_instance(data_dir: Path) -> None:
    first = tray.acquire_lock()
    assert first is not None
    try:
        assert tray.acquire_lock() is None
    finally:
        tray.release_lock(first)
    second = tray.acquire_lock()
    assert second is not None
    tray.release_lock(second)
    assert not (data_dir / tray.LOCK_NAME).exists()


def test_stale_lock_is_replaced(data_dir: Path) -> None:
    path = data_dir / tray.LOCK_NAME
    path.write_text(json.dumps({"pid": 999999999, "create_time": 1.0}), "utf-8")
    lock = tray.acquire_lock()
    assert lock is not None
    tray.release_lock(lock)
    assert not path.exists()


def test_fresh_unreadable_lock_is_respected(data_dir: Path) -> None:
    # 另一个实例刚创建锁文件、内容还没写完：不能抢。
    (data_dir / tray.LOCK_NAME).write_text("", "utf-8")
    assert tray.acquire_lock() is None


def test_send_open_without_tray(data_dir: Path) -> None:
    with pytest.raises(tray.TrayUnavailable):
        tray.send_open(1.0)


def test_ipc_round_trip(data_dir: Path) -> None:
    server = tray.IpcServer(lambda command: f"handled {command}", "token")
    server.start()
    tray._write_info(
        {
            "pid": os.getpid(),
            "create_time": psutil.Process().create_time(),
            "port": server.port,
            "token": "token",
        }
    )
    try:
        assert tray.running() == (os.getpid(), server.port)
        assert tray.send_open(5.0) == "handled open"
    finally:
        server.close()
        tray._clear_info()
    assert tray.running() is None


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


def test_show_details_opens_dialog(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tray.TrayApp(Settings())
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(app.controller, "describe", lambda: "服务: 运行中\nPID : 1")
    monkeypatch.setattr(
        tray.platform,
        "load",
        lambda: SimpleNamespace(message=lambda title, text, **kwargs: calls.append((title, text))),
    )
    app._details_lock.acquire()
    app._show_details()
    assert calls == [("DeepSeek Harness 服务状态", "服务: 运行中\nPID : 1")]
    assert app._details_lock.acquire(blocking=False)


def test_show_details_reports_describe_failure(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tray.TrayApp(Settings())
    calls: list[tuple[str, str]] = []

    def boom() -> str:
        raise RuntimeError("no state")

    monkeypatch.setattr(app.controller, "describe", boom)
    monkeypatch.setattr(
        tray.platform,
        "load",
        lambda: SimpleNamespace(message=lambda title, text, **kwargs: calls.append((title, text))),
    )
    app._details_lock.acquire()
    app._show_details()
    assert calls and calls[0][1].startswith("读取状态失败")
    assert app._details_lock.acquire(blocking=False)


def test_show_details_notifies_when_dialog_fails(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = tray.TrayApp(Settings())
    notified: list[str] = []

    def boom(title: str, text: str, **kwargs: object) -> None:
        raise RuntimeError("no dialog")

    monkeypatch.setattr(app.controller, "describe", lambda: "服务: 未运行")
    monkeypatch.setattr(tray.platform, "load", lambda: SimpleNamespace(message=boom))
    monkeypatch.setattr(app, "_notify", lambda text: notified.append(text))
    app._details_lock.acquire()
    app._show_details()
    assert notified and "打开状态窗口失败" in notified[0]
    assert app._details_lock.acquire(blocking=False)
