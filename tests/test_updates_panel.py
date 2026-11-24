"""更新面板 HTTP：页面、token、升级 POST。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from weblauncher.paths import Paths
from weblauncher.services.dsh import panel as updates_panel
from weblauncher.services.dsh import updates
from weblauncher.services.dsh.settings import Settings


def _report() -> updates.UpdateReport:
    dsh = updates.DshUpdate(
        "@deepseek-ai/dsh",
        "0.2.2-rc.2",
        "0.2.2-rc.5",
        True,
        True,
        "npm",
        "npm install -g @deepseek-ai/dsh@0.2.2-rc.5",
    )
    plugin = updates.PluginUpdate("dsh-context", "^0.84.0", "0.84.0", "0.84.1", "0.87.1", "update", "")
    return updates.UpdateReport(
        "2026-11-23T00:00:00",
        dsh,
        updates.ProfileReport("web", "/tmp/web", 1, (plugin,)),
    )


@pytest.fixture
def panel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    context = SimpleNamespace(
        settings=Settings(),
        paths=Paths(tmp_path),
        backend=SimpleNamespace(),
        service=lambda: SimpleNamespace(status=lambda **kwargs: SimpleNamespace(running=False, pid=None)),
    )
    server = updates_panel.PanelServer(context)  # type: ignore[arg-type]
    monkeypatch.setattr(server, "check", lambda refresh=False: _report())
    server.start()
    yield server
    server.close()


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read()


def _post(url: str, payload: dict, token: str | None, *, origin: str | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Panel-Token"] = token
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_page_and_updates_api(panel: updates_panel.PanelServer) -> None:
    status, body = _get(panel.url)
    assert status == 200
    assert "DeepSeek Harness 更新".encode() in body

    status, body = _get(panel.url + "api/updates")
    assert status == 200
    payload = json.loads(body)
    assert payload["update_count"] == 2
    assert payload["profile"]["plugins"][0]["name"] == "dsh-context"


def test_upgrade_requires_token(panel: updates_panel.PanelServer) -> None:
    status, payload = _post(panel.url + "api/upgrade", {"targets": ["dsh"]}, None)
    assert status == 403
    assert payload["error"] == "unauthorized"

    status, payload = _post(panel.url + "api/upgrade", {"targets": ["dsh"]}, "wrong")
    assert status == 403


def test_upgrade_passes_targets(panel: updates_panel.PanelServer, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_start(targets: list[str], report: updates.UpdateReport) -> dict:
        calls.append(targets)
        return {"status": "running", "targets": targets}

    monkeypatch.setattr(panel.manager, "start", fake_start)

    status, payload = _post(panel.url + "api/upgrade", {"targets": ["dsh"]}, panel.token)

    assert status == 202
    assert payload["status"] == "running"
    assert calls == [["dsh"]]


def test_upgrade_rejects_bad_body(panel: updates_panel.PanelServer) -> None:
    status, payload = _post(panel.url + "api/upgrade", {"targets": "dsh"}, panel.token)
    assert status == 400
    assert "targets" in payload["error"]


def test_open_window_uses_separate_profile(
    panel: updates_panel.PanelServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_launch(settings, url, **kwargs):
        captured["settings"] = settings
        captured["url"] = url
        return "new"

    monkeypatch.setattr(updates_panel.browser, "launch", fake_launch)
    assert panel.open_window() == "new"
    assert captured["settings"].profile_dir == panel.context.paths.panel_profile
    assert captured["url"].startswith("http://127.0.0.1:")
    assert panel.token not in captured["url"]


def test_upgrade_accepts_localhost_origin(
    panel: updates_panel.PanelServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel.manager, "start", lambda targets, report: {"status": "running"})
    origin = f"http://localhost:{panel.port}"
    status, payload = _post(
        panel.url + "api/upgrade",
        {"targets": ["dsh"]},
        panel.token,
        origin=origin,
    )
    assert status in {202, 409, 400}
    assert "forbidden origin" not in payload.get("error", "")
