"""启动过场页的本地 HTTP 生命周期。"""

from __future__ import annotations

import json
from http.client import HTTPConnection

from weblauncher.splash import SplashServer


def _get(server: SplashServer, path: str) -> tuple[int, bytes]:
    conn = HTTPConnection("127.0.0.1", server.port, timeout=5)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_splash_page_and_ready() -> None:
    server = SplashServer()
    server.start()
    try:
        status, body = _get(server, f"/{server.token}/")
        assert status == 200
        assert "正在启动服务" in body.decode("utf-8")

        status, body = _get(server, f"/{server.token}/status")
        assert status == 200
        assert json.loads(body) == {"state": "starting"}

        server.ready("http://127.0.0.1:18080/?token=x")
        status, body = _get(server, f"/{server.token}/status")
        assert status == 200
        assert json.loads(body) == {"state": "ready", "url": "http://127.0.0.1:18080/?token=x"}
        assert server.wait_delivered(1)
    finally:
        server.close()


def test_splash_error_and_unknown_path() -> None:
    server = SplashServer()
    server.start()
    try:
        status, body = _get(server, f"/{server.token}/status")
        assert status == 200 and json.loads(body)["state"] == "starting"

        server.fail("boom")
        status, body = _get(server, f"/{server.token}/status")
        assert status == 200 and json.loads(body) == {"state": "error", "message": "boom"}

        status, _ = _get(server, "/wrong/")
        assert status == 404
    finally:
        server.close()
