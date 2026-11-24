"""Jupyter 适配器：argv/env/token、进程归属、HTTP 就绪与关闭。"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from weblauncher.services.jupyter.adapter import JupyterAdapter
from weblauncher.services.jupyter.discovery import Install
from weblauncher.services.jupyter.settings import Settings


def _adapter(tmp_path: Path, **overrides) -> JupyterAdapter:
    overrides.setdefault("token", "fixed")
    settings = Settings(root_dir=tmp_path, **overrides)
    return JupyterAdapter(settings, Install((sys.executable,), None, None, None))


def test_prepare_uses_token_env_and_deterministic_flags(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, port=18888, base_url="/lab2/", kernel="proj")
    plan = adapter.prepare(host="127.0.0.1", port=18888)
    assert plan.token == "fixed"
    assert plan.env["JUPYTER_TOKEN"] == "fixed"
    assert "--no-browser" in plan.argv
    assert "--ServerApp.port=18888" in plan.argv
    assert "--ServerApp.port_retries=0" in plan.argv
    assert f"--ServerApp.root_dir={tmp_path}" in plan.argv
    assert "--ServerApp.base_url=/lab2/" in plan.argv
    assert "--MappingKernelManager.default_kernel_name=proj" in plan.argv
    assert plan.url == "http://127.0.0.1:18888/lab2/lab?token=fixed"


def test_prepare_rejects_missing_root(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path / "missing")
    with pytest.raises(RuntimeError, match="工作目录不存在"):
        adapter.prepare(host="127.0.0.1", port=18888)


def test_owns_process_matches_port(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    line = r'"C:\...\python.exe" -m jupyterlab --ServerApp.port=18888'
    assert adapter.owns_process(line, 18888)
    assert not adapter.owns_process(line, 18889)
    assert not adapter.owns_process("python other.py --port=18888", 18888)


class _Handler(BaseHTTPRequestHandler):
    token = "fixed"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"token {self.token}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/base/api/status" and self._authorized():
            body = b'{"started": true}'
            self.send_response(200)
        else:
            body = b"forbidden"
            self.send_response(403)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/base/api/shutdown" and self._authorized():
            self.send_response(200)
        else:
            self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def test_ready_and_shutdown(tmp_path: Path, server) -> None:
    port = int(server.server_address[1])
    adapter = _adapter(tmp_path, port=port, base_url="/base/")
    plan = adapter.prepare(host="127.0.0.1", port=port)
    state = SimpleNamespace(port=port, token=plan.token)
    assert adapter.ready(plan, state, port_open=lambda value: True, log_text=lambda: "") == plan.url
    assert adapter.request_stop(state) is True

    bad = _adapter(tmp_path, port=port, base_url="/base/", token="wrong")
    bad_plan = bad.prepare(host="127.0.0.1", port=port)
    assert bad.ready(bad_plan, state, port_open=lambda value: True, log_text=lambda: "") is None
    assert bad.request_stop(SimpleNamespace(port=port, token="wrong")) is False


def test_start_failure_translates_port_conflict(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    text = "OSError: [Errno 10048] Address already in use"
    detail = adapter.start_failure(text, 8888)
    assert "8888" in detail
    assert "--port 8889" in detail


def test_status_extra_and_doctor_rows(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, kernel="proj", base_url="/")
    extra = adapter.status_extra(SimpleNamespace())
    assert extra["root_dir"] == str(tmp_path)
    assert extra["kernel"] == "proj"
    labels = [label for label, _ in adapter.doctor_rows()]
    assert "jupyter-lab" in labels
    assert "root_dir" in labels


def test_ready_requires_open_port(tmp_path: Path, server) -> None:
    port = int(server.server_address[1])
    adapter = _adapter(tmp_path, port=port, base_url="/base/")
    plan = adapter.prepare(host="127.0.0.1", port=port)
    state = SimpleNamespace(port=port, token=plan.token)
    assert adapter.ready(plan, state, port_open=lambda value: False, log_text=lambda: "") is None


def test_port_zero_is_recovered_from_log(tmp_path: Path, server) -> None:
    port = int(server.server_address[1])
    adapter = _adapter(tmp_path, port=0, base_url="/base/")
    plan = adapter.prepare(host="127.0.0.1", port=0)
    state = SimpleNamespace(port=0, token=plan.token)
    log = f"[launcher] start port=0 at=now\n[I] http://127.0.0.1:{port}/base/lab?token=...\n"
    url = adapter.ready(plan, state, port_open=lambda value: True, log_text=lambda: log)
    assert state.port == port
    assert url == f"http://127.0.0.1:{port}/base/lab?token=fixed"


def test_owns_port_zero_process(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    line = '"python.exe" -m jupyterlab --ServerApp.port=0'
    assert adapter.owns_process(line, 54321)


def test_ready_ignores_previous_run_url(tmp_path: Path, server) -> None:
    port = int(server.server_address[1])
    adapter = _adapter(tmp_path, port=0, base_url="/base/")
    plan = adapter.prepare(host="127.0.0.1", port=0)
    state = SimpleNamespace(port=0, token=plan.token)
    text = (
        "[launcher] start port=0 at=old\n"
        "http://127.0.0.1:11111/base/lab?token=old\n"
        f"[launcher] start port=0 at=now\n[I] http://127.0.0.1:{port}/base/lab?token=...\n"
    )
    url = adapter.ready(plan, state, port_open=lambda value: value == port, log_text=lambda: text)
    assert state.port == port
    assert url is not None and f":{port}" in url


def test_marker_escapes_braced_root(tmp_path: Path) -> None:
    root = tmp_path / "{proj}"
    root.mkdir()
    adapter = _adapter(root)
    plan = adapter.prepare(host="127.0.0.1", port=1)
    assert str(root) in plan.marker.format(port=1, at="now")


def test_ready_parses_ipv6_port_zero_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    from weblauncher.services.jupyter import adapter as jupyter_adapter

    adapter = _adapter(tmp_path, port=0, base_url="/base/")
    plan = adapter.prepare(host="::", port=0)
    state = SimpleNamespace(port=0, token=plan.token)
    text = "[launcher] start port=0 at=now\n[I] http://[::1]:54321/base/lab?token=...\n"
    monkeypatch.setattr(jupyter_adapter, "_LOOPBACK_OPENER", Opener())
    url = adapter.ready(plan, state, port_open=lambda value: value == 54321, log_text=lambda: text)
    assert state.port == 54321
    assert url is not None and "[::1]" in url


def test_status_extra_prefers_running_state(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, kernel="new")
    state = SimpleNamespace(extra={"root_dir": str(tmp_path / "old"), "kernel": "old"})
    extra = adapter.status_extra(state)
    assert extra["root_dir"] == str(tmp_path / "old")
    assert extra["kernel"] == "old"
