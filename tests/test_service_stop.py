"""stop 只处理可信实例/端口，并在端口未释放时保留 state。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dshlauncher import paths, service
from dshlauncher.settings import Settings


@pytest.fixture(autouse=True)
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    return tmp_path / "state.json"


def test_stop_uses_state_port_and_removes_state(state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file.write_text("{}", "utf-8")
    controller = service.Service(Settings())
    state = service.State(pid=123, create_time=1.0, port=18080)
    killed: list[int] = []
    waits: list[int] = []

    monkeypatch.setattr(controller, "read_state", lambda: state)
    monkeypatch.setattr(controller, "live_process", lambda value: SimpleNamespace(pid=123))
    monkeypatch.setattr(controller, "_kill_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(controller, "_wait_port_closed", lambda port: waits.append(port))
    monkeypatch.setattr(controller, "port_open", lambda port=None: False)

    assert controller.stop() is True
    assert killed == [123]
    assert waits == [18080]
    assert not state_file.exists()


def test_stop_does_not_kill_foreign_listener(state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = service.Service(Settings())
    killed: list[int] = []

    monkeypatch.setattr(controller, "read_state", lambda: None)
    monkeypatch.setattr(controller, "live_process", lambda value: None)
    monkeypatch.setattr(controller, "port_owner_process", lambda port=None: SimpleNamespace(pid=9))
    monkeypatch.setattr(controller, "_is_dsh_process", lambda proc: False)
    monkeypatch.setattr(controller, "_kill_tree", lambda pid: killed.append(pid))

    assert controller.stop() is False
    assert killed == []
    assert not state_file.exists()


def test_stop_checks_last_known_port_for_stale_state(
    state_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller = service.Service(Settings())
    state = service.State(pid=1, create_time=1.0, port=18080)
    killed: list[int] = []

    def owner(port: int | None = None):  # noqa: ANN202 - 测试替身
        return SimpleNamespace(pid=77) if port == 18080 else None

    monkeypatch.setattr(controller, "read_state", lambda: state)
    monkeypatch.setattr(controller, "live_process", lambda value: None)
    monkeypatch.setattr(controller, "port_owner_process", owner)
    monkeypatch.setattr(controller, "_is_dsh_process", lambda proc: True)
    monkeypatch.setattr(controller, "_kill_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(controller, "_wait_port_closed", lambda port: None)
    monkeypatch.setattr(controller, "port_open", lambda port=None: False)

    assert controller.stop() is True
    assert killed == [77]


def test_stop_keeps_state_when_port_stays_open(state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_file.write_text("{}", "utf-8")
    controller = service.Service(Settings())
    state = service.State(pid=123, create_time=1.0, port=18080)

    monkeypatch.setattr(controller, "read_state", lambda: state)
    monkeypatch.setattr(controller, "live_process", lambda value: SimpleNamespace(pid=123))
    monkeypatch.setattr(controller, "_kill_tree", lambda pid: None)
    monkeypatch.setattr(controller, "_wait_port_closed", lambda port: None)
    monkeypatch.setattr(controller, "port_open", lambda port=None: True)
    monkeypatch.setattr(controller, "port_owner", lambda port=None: "pid 9 foreign")

    with pytest.raises(RuntimeError, match="state.json 已保留"):
        controller.stop()
    assert state_file.exists()


def test_stop_checks_planned_port_without_state(state_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller = service.Service(Settings())
    killed: list[int] = []

    def owner(port: int | None = None):  # noqa: ANN202 - 测试替身
        return SimpleNamespace(pid=88) if port == 18080 else None

    monkeypatch.setattr(controller, "read_state", lambda: None)
    monkeypatch.setattr(controller, "live_process", lambda value: None)
    monkeypatch.setattr(controller, "effective_port", lambda: 18080)
    monkeypatch.setattr(controller, "port_owner_process", owner)
    monkeypatch.setattr(controller, "_is_dsh_process", lambda proc: True)
    monkeypatch.setattr(controller, "_kill_tree", lambda pid: killed.append(pid))
    monkeypatch.setattr(controller, "_wait_port_closed", lambda port: None)
    monkeypatch.setattr(controller, "port_open", lambda port=None: False)

    assert controller.stop() is True
    assert killed == [88]
