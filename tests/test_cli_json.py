"""status/doctor 的 JSON 输出与解析器开关。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dshlauncher import __main__ as cli
from dshlauncher import doctor, paths


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
