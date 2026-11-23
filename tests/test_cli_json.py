"""status/doctor 的 JSON 输出与解析器开关。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dshlauncher import __main__ as cli
from dshlauncher import doctor, paths, updates


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSHLAUNCHER_HOME", str(tmp_path))
    monkeypatch.delenv("DSHLAUNCHER_PORT", raising=False)
    paths.data_dir.cache_clear()
    yield
    paths.data_dir.cache_clear()


def test_status_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["running"] is False
    assert data["port"] == 3080
    assert data["host"] == "127.0.0.1"


def test_doctor_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(doctor, "report", lambda context: [("a", "b"), ("c", "d")])
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


def test_updates_panel_delegates_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from dshlauncher import updates_panel

    calls: dict = {}

    def fake_run(context, *, profile: str, timeout: float) -> int:
        calls.update(profile=profile, timeout=timeout)
        return 0

    monkeypatch.setattr(updates_panel, "run", fake_run)
    assert cli.main(["updates", "--panel", "--profile", "dsh-tui", "--timeout", "5"]) == 0
    assert calls == {"profile": "dsh-tui", "timeout": 5.0}
