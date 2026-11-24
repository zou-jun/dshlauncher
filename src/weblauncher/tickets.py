"""一次性浏览器跳转：让 token 不进入 Chromium 的命令行。"""

from __future__ import annotations

import contextlib
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    token: str
    target: str
    ticket: TicketServer
    consumed: threading.Event
    delivered: threading.Event
    consume_lock: threading.Lock


class _Handler(BaseHTTPRequestHandler):
    server: _Httpd  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 基类签名
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server 接口
        with self.server.consume_lock:
            reusable = self.server.consumed.is_set()
            if urlsplit(self.path).path != f"/{self.server.token}/" or reusable:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.server.consumed.set()
        target = self.server.target
        self.send_response(302)
        self.send_header("Location", target)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.server.delivered.set()
        threading.Timer(1.0, self.server.ticket.close).start()


class TicketServer:
    """短命的 loopback 跳转页：argv 里只有随机 ticket，没有服务 token。"""

    def __init__(self, target: str) -> None:
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"非法跳转目标：{target!r}")
        self.target = target
        self.token = secrets.token_hex(16)
        httpd = _Httpd(("127.0.0.1", 0), _Handler)
        httpd.token = self.token
        httpd.target = target
        httpd.consumed = threading.Event()
        httpd.consume_lock = threading.Lock()
        httpd.delivered = threading.Event()
        httpd.ticket = self  # type: ignore[attr-defined]
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, name="launcher-ticket", daemon=True)
        self._closed = False
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        with contextlib.suppress(Exception):
            self._httpd.shutdown()
        with contextlib.suppress(Exception):
            self._httpd.server_close()

    def close_later(self, delay: float = 15.0) -> None:
        timer = threading.Timer(delay, self.close)
        timer.daemon = True
        timer.start()
