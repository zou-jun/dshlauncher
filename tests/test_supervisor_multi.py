"""跨服务端口排除与通用 Supervisor 的端口规划。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from weblauncher import paths, ports
from weblauncher.services.base import LaunchPlan, ServiceSpec
from weblauncher.supervisor import Supervisor


class Adapter:
    spec = ServiceSpec("demo", "Demo", 18080, fallback_ports=(18081, 18082))
    settings = SimpleNamespace(host="127.0.0.1", port=18080, port_explicit=False, start_timeout=1.0)

    def prepare(self, *, host: str, port: int) -> LaunchPlan:
        return LaunchPlan([], {}, Path("."))

    def ready(self, plan, state, *, port_open, log_text):  # noqa: ANN001
        return None

    def request_stop(self, state) -> bool:  # noqa: ANN001
        return False

    def owns_process(self, cmdline: str, port: int | None = None) -> bool:
        return False

    def start_failure(self, log_text: str, port: int) -> str:
        return ""

    def url_from_log(self, log_text: str) -> str | None:
        return None

    def work_dir(self) -> Path:
        return Path(".")

    def status_extra(self, state) -> dict[str, str]:  # noqa: ANN001
        return {}

    def doctor_rows(self) -> list[tuple[str, str]]:
        return []


def test_other_service_ports_are_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ports, "probe", lambda host, port: ports.Verdict(ports.FREE))
    controller = Supervisor(
        Adapter(),
        paths_=paths.Paths(tmp_path),
        backend=SimpleNamespace(),
        other_ports=lambda: {18080},
    )
    assert controller.effective_port() == 18081


def test_own_previous_port_is_preferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ports, "probe", lambda host, port: ports.Verdict(ports.FREE))
    service = paths.Paths(tmp_path).service("demo")
    service.ensure()
    service.state.write_text('{"pid": 1, "create_time": 0, "port": 18082, "url": null}', "utf-8")
    controller = Supervisor(Adapter(), paths_=paths.Paths(tmp_path), backend=SimpleNamespace())
    assert controller.effective_port() == 18082


def test_port_open_maps_wildcard_to_loopback(tmp_path: Path) -> None:
    import socket

    server = socket.socket()
    server.bind(("0.0.0.0", 0))
    server.listen(1)
    port = int(server.getsockname()[1])
    adapter = Adapter()
    adapter.settings = SimpleNamespace(host="0.0.0.0", port=port, port_explicit=False, start_timeout=1.0)
    try:
        assert Supervisor(adapter, paths_=paths.Paths(tmp_path)).port_open(port)
    finally:
        server.close()
