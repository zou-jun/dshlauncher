"""Web 控制台：一次性入口、会话、API 与任务。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from weblauncher import paths
from weblauncher.context import Runtime
from weblauncher.control.backend import ControlBackend, ControlError
from weblauncher.control.server import ControlServer
from weblauncher.controller import ServiceController, ServiceControllerRegistry


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@pytest.fixture
def console(tmp_path: Path):
    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    controllers = {context.service_id: ServiceController(context) for context in runtime.contexts()}
    backend = ControlBackend(runtime, controllers)
    server = ControlServer(backend)
    server.start()
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(server.bootstrap_url("/#/"))
    except urllib.error.HTTPError as error:
        cookie = (error.headers.get("Set-Cookie") or "").split(";", 1)[0]
        target = error.headers.get("Location")
    else:  # pragma: no cover - 防御性
        raise AssertionError("bootstrap 必须重定向")
    try:
        yield server, cookie, target
    finally:
        server.close()


def _call(server: ControlServer, cookie: str, path: str, *, method: str = "GET", body=None, csrf=True):
    headers = {"Cookie": cookie, "Host": f"127.0.0.1:{server.port}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        headers["Origin"] = server.base_url
        if csrf:
            headers["X-CSRF-Token"] = server.csrf
    request = urllib.request.Request(server.base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_bootstrap_sets_cookie_and_cannot_be_reused(console) -> None:
    server, cookie, target = console
    assert target == "/#/"
    assert cookie.startswith("weblauncher_session=")
    status, payload = _call(server, cookie, "/api/meta")
    assert status == 200
    assert payload["csrf"] == server.csrf
    assert payload["pid"]


def test_unauthenticated_and_csrf_rejected(console) -> None:
    server, cookie, _ = console
    status, _ = _call(server, "bad", "/api/meta")
    assert status == 401
    status, payload = _call(
        server,
        cookie,
        "/api/config/value",
        method="PUT",
        body={"key": "ui.dedupe", "value": False},
        csrf=False,
    )
    assert status == 403
    assert payload["error"] == "forbidden request"


def test_static_and_service_api(console) -> None:
    server, cookie, _ = console
    request = urllib.request.Request(
        server.base_url + "/", headers={"Cookie": cookie, "Host": f"127.0.0.1:{server.port}"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
    assert b"Web" in body
    status, payload = _call(server, cookie, "/api/services")
    assert status == 200
    assert {item["id"] for item in payload["services"]} == {"dsh", "jupyter"}
    assert all("token=" not in (item.get("url") or "") for item in payload["services"])


def test_doctor_splits_general_and_services(console) -> None:
    server, cookie, _ = console
    status, payload = _call(server, cookie, "/api/doctor")
    assert status == 200
    assert {"启动器", "Python"} <= {row["name"] for row in payload["general"]}
    assert {item["id"] for item in payload["services"]} == {"dsh", "jupyter"}
    assert all(
        not row["name"].startswith(("dsh ·", "jupyter ·"))
        for item in payload["services"]
        for row in item["rows"]
    )


def test_doctor_can_scope_to_general_only(console) -> None:
    server, cookie, _ = console
    status, payload = _call(server, cookie, "/api/doctor", method="POST", body={"services": []})
    assert status == 202
    for _ in range(30):
        status, job = _call(server, cookie, f"/api/jobs/{payload['id']}")
        if job["status"] != "running":
            break
    assert job["status"] == "succeeded"
    assert {"启动器", "Python"} <= {row["name"] for row in job["result"]["general"]}
    assert job["result"]["services"] == []


def test_service_cards_expose_relative_tools(console) -> None:
    server, cookie, _ = console
    status, payload = _call(server, cookie, "/api/services")
    assert status == 200
    tools = {
        item["id"]: {(tool["slug"], tool["label"]) for tool in item["tools"]} for item in payload["services"]
    }
    assert ("updates", "更新") in tools["dsh"]
    assert ("kernels", "内核") in tools["jupyter"]
    assert ("workdirs", "工作目录") in tools["jupyter"]
    icons = {item["id"]: item["icon"] for item in payload["services"]}
    assert icons == {"dsh": "dsh", "jupyter": "jupyter"}


def test_unavailable_service_stays_in_overview(tmp_path: Path) -> None:
    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    context = runtime.context("dsh")
    registry = ServiceControllerRegistry(
        {"dsh": ServiceController(context)},
        errors={"jupyter": "RuntimeError: jupyter 配置无效"},
    )
    rows = ControlBackend(runtime, registry).services()
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == {"dsh", "jupyter"}
    assert by_id["jupyter"]["status"] == "error"
    assert by_id["jupyter"]["label"] == "Jupyter Lab"
    assert by_id["jupyter"]["tools"]
    assert "配置无效" in by_id["jupyter"]["error"]


def test_reload_preserves_unavailable_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from weblauncher.services import registry as service_registry

    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    controllers = {context.service_id: ServiceController(context) for context in runtime.contexts()}
    backend = ControlBackend(runtime, controllers)
    real_build = service_registry.build

    def build(runtime_, service_id, *, cli=None):  # noqa: ANN001, ANN202
        if service_id == "jupyter":
            raise RuntimeError("jupyter 配置无效")
        return real_build(runtime_, service_id, cli=cli)

    monkeypatch.setattr(service_registry, "build", build)
    backend._reload()
    assert backend.controllers.get("jupyter") is None
    assert "配置无效" in backend.controllers.errors()["jupyter"]
    assert {row["id"] for row in backend.services()} == {"dsh", "jupyter"}


def test_split_js_modules_are_served(console) -> None:
    server, cookie, _ = console
    for path in ("/core.js", "/pages/settings.js", "/pages/jupyter.js"):
        request = urllib.request.Request(
            server.base_url + path,
            headers={"Cookie": cookie, "Host": f"127.0.0.1:{server.port}"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read()
        assert response.status == 200
        assert body


def test_async_diagnostic_and_update_jobs(console, monkeypatch: pytest.MonkeyPatch) -> None:
    server, cookie, _ = console
    backend = server.backend
    monkeypatch.setattr(backend, "doctor", lambda services=None: {"general": [], "services": []})
    monkeypatch.setattr(backend, "updates", lambda **kwargs: {"checked_at": "now"})
    for path, expected in (
        ("/api/doctor", {"general": [], "services": []}),
        ("/api/updates", {"checked_at": "now"}),
    ):
        status, payload = _call(server, cookie, path, method="POST", body={})
        assert status == 202
        for _ in range(30):
            status, job = _call(server, cookie, f"/api/jobs/{payload['id']}")
            if job["status"] != "running":
                break
        assert job["status"] == "succeeded"
        assert job["result"] == expected


def test_static_module_path_cannot_escape_root(console) -> None:
    server, cookie, _ = console
    request = urllib.request.Request(
        server.base_url + "/pages/%2e%2e/%2e%2e/app.js",
        headers={"Cookie": cookie, "Host": f"127.0.0.1:{server.port}"},
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=10)
    assert caught.value.code == 404


def test_config_round_trip_and_path_serialization(console) -> None:
    server, cookie, _ = console
    status, payload = _call(server, cookie, "/api/config")
    assert status == 200
    assert payload["path"].endswith("config.toml")
    assert isinstance(payload["values"]["dsh.work_dir"], str)
    status, payload = _call(
        server,
        cookie,
        "/api/config/value",
        method="PUT",
        body={"key": "ui.dedupe", "value": False},
    )
    assert status == 200 and payload["restart_required"]
    status, payload = _call(server, cookie, "/api/config")
    assert payload["values"]["ui.dedupe"] is False
    status, payload = _call(server, cookie, "/api/config/value", method="DELETE", body={"key": "ui.dedupe"})
    assert status == 200 and payload["removed"] is True


def test_action_returns_job(console, monkeypatch: pytest.MonkeyPatch) -> None:
    server, cookie, _ = console
    backend = server.backend
    monkeypatch.setattr(backend, "action", lambda service, action, force=False: f"{action}:{service}")
    status, payload = _call(
        server,
        cookie,
        "/api/actions",
        method="POST",
        body={"action": "start", "services": ["jupyter"]},
    )
    assert status == 202
    job_id = payload["id"]
    for _ in range(30):
        status, job = _call(server, cookie, f"/api/jobs/{job_id}")
        if job["status"] != "running":
            break
    assert job["status"] == "succeeded"
    assert job["result"] == "start:jupyter"


def test_quit_calls_backend(tmp_path: Path) -> None:
    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    controllers = {context.service_id: ServiceController(context) for context in runtime.contexts()}
    calls: list[bool] = []
    backend = ControlBackend(
        runtime, controllers, request_quit=lambda **kwargs: calls.append(kwargs["stop_services"])
    )
    server = ControlServer(backend)
    server.start()
    try:

        class _NoRedirect2(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None

        opener = urllib.request.build_opener(_NoRedirect2())
        try:
            opener.open(server.bootstrap_url())
        except urllib.error.HTTPError as error:
            cookie = error.headers["Set-Cookie"].split(";", 1)[0]
        status, _ = _call(server, cookie, "/api/agent/quit", method="POST", body={"stop_services": True})
        assert status == 200
        for _ in range(40):
            if calls:
                break
            import time

            time.sleep(0.05)
        assert calls == [True]
    finally:
        server.close()


def test_backend_rejects_busy_action(tmp_path: Path) -> None:
    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    context = runtime.context("dsh")
    controller = ServiceController(context)
    backend = ControlBackend(runtime, {"dsh": controller}, request_quit=None)
    controller._busy.acquire()
    try:
        with pytest.raises(ControlError, match="操作正在进行"):
            backend.action("dsh", "start")
    finally:
        controller._busy.release()
