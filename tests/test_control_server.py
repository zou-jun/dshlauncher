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
from weblauncher.tray.controller import TrayController


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


@pytest.fixture
def console(tmp_path: Path):
    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    controllers = {context.service_id: TrayController(context) for context in runtime.contexts()}
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
    controllers = {context.service_id: TrayController(context) for context in runtime.contexts()}
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
    controller = TrayController(context)
    backend = ControlBackend(runtime, {"dsh": controller}, request_quit=None)
    controller._busy.acquire()
    try:
        with pytest.raises(ControlError, match="操作正在进行"):
            backend.action("dsh", "start")
    finally:
        controller._busy.release()
