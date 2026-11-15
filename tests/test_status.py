"""服务状态快照与格式化。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dshlauncher import paths, service
from dshlauncher.settings import Settings
from dshlauncher.status import ServiceStatus

STATUS = ServiceStatus(
    running=True,
    pid=1234,
    host="127.0.0.1",
    port=18080,
    listening=True,
    url="http://127.0.0.1:18080/?token=x",
    work_dir=Path("/tmp/work"),
    data_dir=Path("/tmp/data"),
    log_path=Path("/tmp/data/dsh-web.log"),
)


def test_short_and_tooltip() -> None:
    assert STATUS.short() == "运行中"
    assert STATUS.tooltip() == "运行中 · pid=1234 · 127.0.0.1:18080"
    stopped = ServiceStatus(False, None, "127.0.0.1", 3080, False, None, Path("w"), Path("d"), Path("l"))
    assert stopped.short() == "未运行"
    assert stopped.tooltip() == "未运行"


def test_full_warns_when_foreign_owner() -> None:
    foreign = ServiceStatus(
        False,
        None,
        "127.0.0.1",
        3080,
        True,
        None,
        Path("/tmp/work"),
        Path("/tmp/data"),
        Path("/tmp/data/dsh-web.log"),
        owner="pid 9 other",
    )
    assert "端口被外部进程占用 -> pid 9 other" in foreign.full()
    assert "port held by -> pid 9 other" in foreign.full(english=True)


def test_as_dict_is_json_ready() -> None:
    data = STATUS.as_dict()
    assert data["running"] is True
    assert data["pid"] == 1234
    assert data["port"] == 18080
    assert data["work_dir"] == str(STATUS.work_dir)
    assert data["log"] == str(STATUS.log_path)


def test_service_status_does_not_probe_when_asked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    controller = service.Service(Settings())
    state = service.State(pid=1234, create_time=1.0, port=18080, url="http://x/?token=t")
    monkeypatch.setattr(controller, "read_state", lambda: state)
    monkeypatch.setattr(controller, "live_process", lambda value: type("P", (), {"pid": 1234})())

    def fail(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202 - 不该被调用
        raise AssertionError("不应探测端口")

    monkeypatch.setattr(controller, "port_open", fail)
    monkeypatch.setattr(controller, "latest_url", fail)

    status = controller.status(check_ports=False)
    assert status.running is True
    assert status.port == 18080
    assert status.listening is False
    assert status.url is None
