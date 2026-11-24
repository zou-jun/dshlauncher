"""控制台路由表契约：handler 完整、匹配唯一、方法可达。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from weblauncher import paths
from weblauncher.context import Runtime
from weblauncher.control.backend import ControlBackend
from weblauncher.control.routes import ROUTES
from weblauncher.control.server import ControlServer, _Handler
from weblauncher.controller import ServiceController


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
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            opener.open(server.bootstrap_url("/#/"))
        except urllib.error.HTTPError as error:
            cookie = (error.headers.get("Set-Cookie") or "").split(";", 1)[0]
        else:  # pragma: no cover - 防御性
            raise AssertionError("bootstrap 必须重定向")
        yield server, cookie
    finally:
        server.close()


def _call(server: ControlServer, cookie: str, path: str, *, method: str = "GET", body=None):
    headers = {"Cookie": cookie, "Host": f"127.0.0.1:{server.port}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        headers["Origin"] = server.base_url
        headers["X-CSRF-Token"] = server.csrf
    request = urllib.request.Request(server.base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_route_handlers_exist_and_are_unique() -> None:
    assert ROUTES
    missing = [route.handler for route in ROUTES if not hasattr(_Handler, route.handler)]
    assert missing == []
    seen = {(route.method, route.pattern.pattern) for route in ROUTES}
    assert len(seen) == len(ROUTES)
    assert {route.method for route in ROUTES} == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    api_routes = [route.pattern.pattern for route in ROUTES if route.pattern.pattern.startswith("/api/")]
    assert api_routes


def test_route_method_matrix(console, monkeypatch: pytest.MonkeyPatch) -> None:
    server, cookie = console
    backend = server.backend
    kernel = {"name": "demo", "label": "Demo"}
    monkeypatch.setattr(backend, "action", lambda service, action, force=False: f"{action}:{service}")
    monkeypatch.setattr(backend, "service", lambda service_id: {"id": service_id})
    monkeypatch.setattr(backend, "logs", lambda service_id, tail=200: {"service": service_id, "tail": tail})
    monkeypatch.setattr(backend, "doctor", lambda services=None: {"general": [], "services": []})
    monkeypatch.setattr(backend, "updates", lambda **kwargs: {"checked_at": "now"})
    monkeypatch.setattr(backend, "upgrade_job", lambda: {"status": "idle"})
    monkeypatch.setattr(backend, "kernels", lambda: [kernel])
    monkeypatch.setattr(backend, "add_kernel", lambda payload: kernel)
    monkeypatch.setattr(backend, "use_kernel", lambda name: {"kernel": name})
    monkeypatch.setattr(
        backend, "rename_kernel", lambda name, display: {"name": name, "display_name": display}
    )
    monkeypatch.setattr(backend, "remove_kernel", lambda name, force=False: {"removed": name})
    monkeypatch.setattr(backend, "workdirs", lambda: {"current": "/tmp", "items": []})
    monkeypatch.setattr(backend, "use_workdir", lambda value, kernel=None: {"path": value})
    monkeypatch.setattr(backend, "upgrade", lambda targets, **kwargs: {"status": "running"})
    monkeypatch.setattr(
        backend, "list_dir", lambda value, include_files=False: {"path": value, "entries": []}
    )
    monkeypatch.setattr(backend, "about", lambda: {"version": "test"})
    monkeypatch.setattr(backend, "save_config_raw", lambda raw: {"saved": True})
    monkeypatch.setattr(backend, "set_config_value", lambda key, value: {"key": key, "value": value})
    monkeypatch.setattr(backend, "unset_config_value", lambda key: {"key": key, "removed": True})
    monkeypatch.setattr(backend, "install", lambda **kwargs: {"created": []})
    monkeypatch.setattr(backend, "uninstall", lambda: {"removed": []})

    cases = (
        ("GET", "/api/meta", None, 200),
        ("GET", "/api/services", None, 200),
        ("GET", "/api/services/dsh", None, 200),
        ("GET", "/api/services/dsh/logs?tail=5", None, 200),
        ("GET", "/api/jobs", None, 200),
        ("GET", "/api/jobs/missing", None, 404),
        ("GET", "/api/doctor", None, 200),
        ("GET", "/api/config", None, 200),
        ("GET", "/api/jupyter/kernels", None, 200),
        ("GET", "/api/jupyter/kernels/demo", None, 200),
        ("GET", "/api/jupyter/workdirs", None, 200),
        ("GET", "/api/updates", None, 200),
        ("GET", "/api/upgrade-job", None, 200),
        ("GET", "/api/fs?path=/tmp", None, 200),
        ("GET", "/api/about", None, 200),
        ("POST", "/api/actions", {"action": "start", "services": ["jupyter"]}, 202),
        ("POST", "/api/doctor", {}, 202),
        ("POST", "/api/updates", {}, 202),
        ("POST", "/api/config", {"raw": "[ui]\n"}, 200),
        ("PUT", "/api/config/value", {"key": "ui.dedupe", "value": False}, 200),
        ("DELETE", "/api/config/value", {"key": "ui.dedupe"}, 200),
        ("POST", "/api/jupyter/kernels", {"name": "demo"}, 200),
        ("POST", "/api/jupyter/kernels/demo/use", {}, 200),
        ("PATCH", "/api/jupyter/kernels/demo", {"display_name": "Demo"}, 200),
        ("DELETE", "/api/jupyter/kernels/demo", {"force": True}, 200),
        ("POST", "/api/jupyter/workdirs", {"path": "/tmp"}, 200),
        ("POST", "/api/upgrades", {"targets": ["dsh"]}, 202),
        ("POST", "/api/install", {"services": ["dsh"]}, 200),
        ("POST", "/api/uninstall", {}, 200),
        ("GET", "/api/no-such-route", None, 404),
    )
    for method, path, body, expected in cases:
        status, payload = _call(server, cookie, path, method=method, body=body)
        assert status == expected, (method, path, status, payload)
