"""启动过场：本地 HTTP 页，轮询就绪后跳转到服务 URL。"""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:dark}
html,body{height:100%;margin:0}
body{display:flex;align-items:center;justify-content:center;background:#0f1115;color:#e8e8ea;
     font:15px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.card{max-width:460px;padding:28px 34px;text-align:center}
.spinner{width:34px;height:34px;margin:0 auto 18px;border:3px solid #343a46;
         border-top-color:#6ea8ff;border-radius:50%;animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
h1{font-size:18px;font-weight:600;margin:0 0 6px}
p{color:#a7adb8;margin:0;white-space:pre-wrap}
</style></head>
<body><div class="card"><div class="spinner"></div><h1>__TITLE__</h1>
<p id="msg">正在启动服务…</p></div>
<script>
const base = "__TOKEN__";
async function poll() {
  try {
    const response = await fetch(base + "/status", {cache: "no-store"});
    const data = await response.json();
    if (data.state === "ready") { location.replace(data.url); return; }
    if (data.state === "error") {
      document.getElementById("msg").textContent = data.message;
      document.querySelector(".spinner").style.display = "none";
      return;
    }
  } catch (error) {}
  setTimeout(poll, 500);
}
poll();
</script></body></html>"""


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    token: str
    page: bytes
    state: dict[str, Any]
    lock: threading.Lock
    delivered: threading.Event


class _Handler(BaseHTTPRequestHandler):
    server: Any

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 基类签名
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server 接口
        path = urlsplit(self.path).path
        base = f"/{self.server.token}"
        if path == base + "/":
            self._send(200, self.server.page, "text/html; charset=utf-8")
            return
        if path == base + "/status":
            with self.server.lock:
                payload = dict(self.server.state)
            body = json.dumps(payload, ensure_ascii=False).encode()
            self._send(200, body, "application/json; charset=utf-8")
            if payload.get("state") == "ready":
                self.server.delivered.set()
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")


class SplashServer:
    """只在启动窗口期存在的本地过场页；token 路径避免其它本机页面读取。"""

    def __init__(self, title: str = "服务") -> None:
        self.token = secrets.token_hex(12)
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"state": "starting"}
        self._delivered = threading.Event()
        self._closed = False
        httpd = _Httpd(("127.0.0.1", 0), _Handler)
        httpd.token = self.token
        httpd.page = _PAGE.replace("__TOKEN__", "/" + self.token).replace("__TITLE__", title).encode()
        httpd.state = self._state
        httpd.lock = self._lock
        httpd.delivered = self._delivered
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, name="service-splash", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/"

    def start(self) -> None:
        self._thread.start()

    def ready(self, url: str) -> None:
        with self._lock:
            self._state.clear()
            self._state.update({"state": "ready", "url": url})

    def fail(self, message: str) -> None:
        with self._lock:
            self._state.clear()
            self._state.update({"state": "error", "message": message})

    def wait_delivered(self, timeout: float) -> bool:
        """等浏览器真正拿到 ready/URL，避免短命 CLI 进程先退出。"""
        return self._delivered.wait(timeout)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._httpd.shutdown()
        self._httpd.server_close()

    def close_later(self, delay: float) -> None:
        timer = threading.Timer(delay, self.close)
        timer.daemon = True
        timer.start()
