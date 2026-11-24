"""status/doctor 的 JSON 输出与解析器开关。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weblauncher import __main__ as cli
from weblauncher import doctor, paths
from weblauncher.services.dsh import updates


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBLAUNCHER_HOME", str(tmp_path))
    monkeypatch.delenv("WEBLAUNCHER_DSH_PORT", raising=False)
    paths.data_dir.cache_clear()
    yield
    paths.data_dir.cache_clear()


def test_status_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["status", "dsh", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["running"] is False
    assert data["port"] == 3080
    assert data["host"] == "127.0.0.1"


def test_doctor_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(doctor, "report", lambda runtime, ids: [("a", "b"), ("c", "d")])
    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [{"name": "a", "value": "b"}, {"name": "c", "value": "d"}]


def _update_report(*, update: bool) -> updates.UpdateReport:
    dsh = updates.DshUpdate(
        "@deepseek-ai/dsh",
        "0.2.2-rc.2",
        "0.2.2-rc.5",
        update,
        True,
        "npm",
        "npm install -g @deepseek-ai/dsh@0.2.2-rc.5",
    )
    return updates.UpdateReport(
        "2026-11-23T00:00:00",
        dsh,
        updates.ProfileReport("web", "/tmp/web", 0),
    )


def test_updates_json_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(updates, "check", lambda *args, **kwargs: _update_report(update=True))
    assert cli.main(["updates", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["update_count"] == 1
    assert payload["dsh"]["latest"] == "0.2.2-rc.5"


def test_updates_json_up_to_date(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(updates, "check", lambda *args, **kwargs: _update_report(update=False))
    assert cli.main(["updates", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["update_count"] == 0


def test_updates_panel_opens_control_route(monkeypatch: pytest.MonkeyPatch) -> None:
    from weblauncher import tray

    calls: dict = {}

    def fake_send(paths_, timeout: float, *, target: str = "/#/") -> str:
        calls["target"] = target
        return "http://127.0.0.1:1/boot/ticket"

    monkeypatch.setattr(tray, "send_ui", fake_send)
    monkeypatch.setattr(tray, "open_console_url", lambda runtime, url: calls.setdefault("url", url) or "new")
    assert cli.main(["updates", "--panel", "--profile", "dsh-tui", "--timeout", "5"]) == 0
    assert calls["target"] == "/#/services/dsh/updates?profile=dsh-tui&timeout=5.0"
    assert calls["url"].endswith("/boot/ticket")
