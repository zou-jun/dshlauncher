"""PortInspector：TTL、未知 PID 与扫描失败。"""

from __future__ import annotations

from types import SimpleNamespace

import psutil
import pytest

from weblauncher import inspector


def _conn(port: int = 18080, pid: int | None = 42):
    return SimpleNamespace(
        laddr=SimpleNamespace(port=port),
        status=psutil.CONN_LISTEN,
        pid=pid,
    )


def test_ttl_expiry_rescans_and_reflects_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    connections = [_conn()]
    calls = 0

    def scan(kind: str):
        nonlocal calls
        calls += 1
        return list(connections)

    monkeypatch.setattr(inspector.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(inspector.psutil, "net_connections", scan)
    monkeypatch.setattr(
        inspector.psutil,
        "Process",
        lambda pid: SimpleNamespace(name=lambda: "demo", cmdline=lambda: ["demo"]),
    )
    probe = inspector.PortInspector(ttl=0.5)
    assert probe.owner(18080) == "pid 42 demo :: demo"
    assert calls == 1
    clock[0] += 0.6
    connections.clear()
    assert probe.owner(18080) is None
    assert calls == 2


def test_unknown_pid_and_scan_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspector.psutil, "net_connections", lambda kind: [_conn(pid=None)])
    unknown = inspector.PortInspector(ttl=60)
    assert unknown.owner(18080) == "未知进程（监听 18080）"
    assert unknown.owner_process(18080) is None

    def fail(kind: str):
        raise OSError("access denied")

    monkeypatch.setattr(inspector.psutil, "net_connections", fail)
    broken = inspector.PortInspector(ttl=60)
    assert broken.owner(18080) is None
    assert broken.owner_process(18080) is None


def test_dead_process_keeps_pid_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inspector.psutil, "net_connections", lambda kind: [_conn(pid=42)])

    def dead(pid: int):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(inspector.psutil, "Process", dead)
    probe = inspector.PortInspector(ttl=60)
    assert probe.owner_process(18080) is None
    assert probe.owner(18080) == "pid 42"
