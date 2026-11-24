from collections.abc import Iterator
from pathlib import Path

import pytest

from weblauncher import paths, ports
from weblauncher.services.dsh import service
from weblauncher.services.dsh.settings import Settings

LOG = """[launcher] start port=3080 at=2026-11-13 10:00:00

dsh: startup failed: 2 required plugins did not activate

Failed plugins (1):
  webserver (required)
    Package: @deepseek-ai/dsh-host-webserver
    Error: listen EACCES: permission denied 127.0.0.1:3080
        at Server.setupListenHandle [as _listen2] (node:net:2145:21)

Plugins waiting for services (15):
  web-runtime (required)        webServer
  better-sidebar                webServer
"""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("WEBLAUNCHER_HOME", str(tmp_path))
    for name in ("PORT", "HOST", "CWD", "BROWSER", "NO_DEDUPE"):
        monkeypatch.delenv("WEBLAUNCHER_DSH_" + name, raising=False)
    paths.data_dir.cache_clear()
    ports.excluded_ranges.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()
    # 有的测试会把 excluded_ranges 换成 lambda，回收时只清真实实现。
    cache_clear = getattr(ports.excluded_ranges, "cache_clear", None)
    if cache_clear is not None:
        cache_clear()


def _verdicts(mapping: dict[int, ports.Verdict]) -> object:
    def fake(host: str, port: int) -> ports.Verdict:
        return mapping.get(port, ports.Verdict(ports.FREE))

    return fake


def test_startup_failure_keeps_the_cause_not_the_plugin_table() -> None:
    reason = service.startup_failure(LOG)
    assert "EACCES" in reason
    assert "webserver (required)" in reason
    assert "Plugins waiting" not in reason
    assert "at Server.setupListenHandle" not in reason


def test_startup_failure_falls_back_to_tail() -> None:
    assert service.startup_failure("boot\nmodel listing loaded\n", lines=2) == "boot\nmodel listing loaded"


def test_url_port() -> None:
    assert service.url_port("http://127.0.0.1:18080/?token=x") == 18080
    assert service.url_port("not a url") is None


def test_default_port_falls_back_when_reserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ports,
        "probe",
        _verdicts(
            {
                3080: ports.Verdict(ports.RESERVED, "2987-3086"),
                18080: ports.Verdict(ports.FREE),
            }
        ),
    )
    controller = service.Service(Settings())
    assert controller.effective_port() == 18080


def test_reuses_port_from_state(monkeypatch: pytest.MonkeyPatch) -> None:
    paths.Paths.current().service("dsh").ensure()
    paths.state_path().write_text('{"pid": 1, "create_time": 0.0, "port": 18081, "url": null}', "utf-8")
    monkeypatch.setattr(ports, "probe", _verdicts({18081: ports.Verdict(ports.FREE)}))
    assert service.Service(Settings()).effective_port() == 18081


def test_explicit_port_is_never_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ports,
        "probe",
        _verdicts({3080: ports.Verdict(ports.RESERVED, "2987-3086"), 18080: ports.Verdict(ports.FREE)}),
    )
    controller = service.Service(Settings(port=3080, port_explicit=True))
    assert controller.effective_port() == 3080


def test_start_refuses_reserved_port_with_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ports, "excluded_ranges", lambda: ((2987, 3086),))
    monkeypatch.setattr(ports, "probe", _verdicts({3080: ports.Verdict(ports.RESERVED, "2987-3086")}))
    controller = service.Service(Settings(port=3080, port_explicit=True))

    with pytest.raises(RuntimeError) as excinfo:
        controller.start()

    message = str(excinfo.value)
    assert "2987-3086" in message
    assert "--port 18080" in message
    assert paths.state_path().exists() is False


def test_skips_port_held_by_a_foreign_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ports,
        "probe",
        _verdicts({3080: ports.Verdict(ports.RESERVED, "2987-3086"), 18080: ports.Verdict(ports.IN_USE)}),
    )
    monkeypatch.setattr(service.Service, "port_owner_process", lambda self, port=None: None)
    # 18080 被占用但不是 dsh：跳过它，落到下一个候选 18081。
    assert service.Service(Settings()).effective_port() == 18081
