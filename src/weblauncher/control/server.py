"""控制台 HTTP 服务：一次性入口、Cookie 会话、JSON API 与静态 SPA。"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .. import __version__
from ..services.dsh import updates as dsh_updates
from .backend import ControlBackend, ControlError
from .jobs import JobManager
from .routes import ROUTES
from .static_assets import StaticAssetError
from .static_assets import read as read_static

COOKIE = "weblauncher_session"
BOOT_TTL = 120.0
MAX_BODY = 1024 * 1024


class _Httpd(ThreadingHTTPServer):
    daemon_threads = True
    control: ControlServer


class _Handler(BaseHTTPRequestHandler):
    server: _Httpd  # type: ignore[assignment]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - 基类签名
        pass

    # ── 通用响应 ──────────────────────────────────────────────────────
    def _send(self, code: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if content_type.startswith("text/html"):
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'",
            )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: Any) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _error(self, exc: BaseException, *, status: int = 500) -> None:
        if isinstance(exc, ControlError):
            status = exc.status
        self._json(status, {"error": str(exc)})

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _cookie_ok(self) -> bool:
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and hmac.compare_digest(value, self.server.control.session):
                return True
        return False

    def _same_origin(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip().lower()
        if origin:
            port = self.server.server_address[1]
            if origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                return False
        site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        return not site or site in {"same-origin", "none"}

    def _csrf_ok(self) -> bool:
        token = self.headers.get("X-CSRF-Token") or ""
        return hmac.compare_digest(token, self.server.control.csrf)

    def _auth(self) -> bool:
        return self._host_ok() and self._cookie_ok()

    # ── 路由 ──────────────────────────────────────────────────────────
    def _dispatch(self, method, path, query, payload):
        for route in ROUTES:
            if route.method != method:
                continue
            match = route.pattern.fullmatch(path)
            if match is None:
                continue
            getattr(self, route.handler)(match.groupdict(), query, payload or {})
            return
        self._json(404, {"error": "not found"})

    def do_GET(self) -> None:  # noqa: N802 - http.server 接口
        parsed = urlsplit(self.path)
        path = parsed.path
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        if path.startswith("/boot/"):
            self._boot(path.removeprefix("/boot/"))
            return
        if not self._cookie_ok():
            if path.startswith("/api/"):
                self._json(401, {"error": "unauthorized"})
            else:
                self._send(401, _LOGIN_PAGE.encode(), "text/html; charset=utf-8")
            return
        try:
            self._dispatch("GET", path, parse_qs(parsed.query), None)
        except Exception as exc:  # noqa: BLE001 - API 必须把具体失败显示在页面
            self._error(exc)

    # ── GET handler ───────────────────────────────────────────────────
    def _index(self, match, query, payload):
        self._static("index.html", "text/html; charset=utf-8")

    def _app_js(self, match, query, payload):
        self._static("app.js", "text/javascript; charset=utf-8")

    def _core_js(self, match, query, payload):
        self._static("core.js", "text/javascript; charset=utf-8")

    def _page_js(self, match, query, payload):
        self._static(f"pages/{unquote(match['name'])}", "text/javascript; charset=utf-8")

    def _styles(self, match, query, payload):
        self._static("styles.css", "text/css; charset=utf-8")

    def _favicon(self, match, query, payload):
        self._send(204, b"", "image/x-icon")

    def _meta_route(self, match, query, payload):
        self._meta()

    def _services(self, match, query, payload):
        self._json(200, {"services": self.server.control.backend.services()})

    def _service_logs(self, match, query, payload):
        service_id = unquote(match["service"])
        tail = _int(query.get("tail", ["200"])[0], 200)
        self._json(200, self.server.control.backend.logs(service_id, tail=tail))

    def _service(self, match, query, payload):
        service_id = unquote(match["service"])
        self._json(200, self.server.control.backend.service(service_id))

    def _jobs(self, match, query, payload):
        self._json(200, {"jobs": self.server.control.jobs.recent()})

    def _job(self, match, query, payload):
        job = self.server.control.jobs.get(match["job_id"])
        if job is None:
            self._json(404, {"error": "任务不存在"})
        else:
            self._json(200, job.as_dict())

    def _doctor_get(self, match, query, payload):
        services = query.get("service", [None])[0]
        wanted = [item for item in (services or "").split(",") if item] or None
        self._json(200, self.server.control.backend.doctor(wanted))

    def _config_get(self, match, query, payload):
        self._json(200, self.server.control.backend.config())

    def _kernels(self, match, query, payload):
        self._json(200, {"kernels": self.server.control.backend.kernels()})

    def _kernel(self, match, query, payload):
        name = unquote(match["name"])
        kernels = self.server.control.backend.kernels()
        found = next((row for row in kernels if row.get("name") == name), None)
        if found is None:
            self._json(404, {"error": f"内核不存在：{name}"})
        else:
            self._json(200, found)

    def _workdirs(self, match, query, payload):
        self._json(200, self.server.control.backend.workdirs())

    def _updates_get(self, match, query, payload):
        profile = query.get("profile", ["web"])[0]
        timeout = _float(query.get("timeout", [str(dsh_updates.DEFAULT_TIMEOUT)])[0])
        refresh = query.get("refresh", ["0"])[0] == "1"
        self._json(
            200,
            self.server.control.backend.updates(refresh=refresh, profile=profile, timeout=timeout),
        )

    def _upgrade_job(self, match, query, payload):
        self._json(200, self.server.control.backend.upgrade_job())

    def _fs(self, match, query, payload):
        value = query.get("path", [""])[0]
        include_files = query.get("files", ["0"])[0] == "1"
        self._json(200, self.server.control.backend.list_dir(value, include_files=include_files))

    def _about(self, match, query, payload):
        self._json(200, self.server.control.backend.about())

    # ── POST/PUT/PATCH/DELETE handler ─────────────────────────────────
    def _actions_post(self, match, query, payload):
        self._action(payload)

    def _quit_post(self, match, query, payload):
        self._quit(payload)

    def _doctor_post(self, match, query, payload):
        services = payload.get("services")
        if services is not None and not isinstance(services, list):
            raise ControlError("services 必须是字符串数组")
        wanted = [str(item) for item in services] if services is not None else None
        job = self.server.control.jobs.submit("诊断", lambda: self.server.control.backend.doctor(wanted))
        self._json(202, job.as_dict())

    def _updates_post(self, match, query, payload):
        profile = str(payload.get("profile") or "web")
        timeout = _float(payload.get("timeout") or dsh_updates.DEFAULT_TIMEOUT)
        refresh = bool(payload.get("refresh"))
        job = self.server.control.jobs.submit(
            "检查更新",
            lambda: self.server.control.backend.updates(refresh=refresh, profile=profile, timeout=timeout),
        )
        self._json(202, job.as_dict())

    def _config_post(self, match, query, payload):
        raw = payload.get("raw")
        if not isinstance(raw, str):
            raise ControlError("raw 必须是字符串")
        self._json(200, self.server.control.backend.save_config_raw(raw))

    def _config_value_put(self, match, query, payload):
        key = str(payload.get("key") or query.get("key", [""])[0])
        if not key:
            raise ControlError("缺少配置键")
        if "value" not in payload:
            raise ControlError("缺少 value")
        self._json(200, self.server.control.backend.set_config_value(key, payload["value"]))

    def _config_value_delete(self, match, query, payload):
        key = str(payload.get("key") or query.get("key", [""])[0])
        if not key:
            raise ControlError("缺少配置键")
        self._json(200, self.server.control.backend.unset_config_value(key))

    def _kernels_post(self, match, query, payload):
        self._json(200, self.server.control.backend.add_kernel(payload))

    def _kernel_use(self, match, query, payload):
        self._json(200, self.server.control.backend.use_kernel(unquote(match["name"])))

    def _kernel_patch(self, match, query, payload):
        display_name = str(payload.get("display_name") or "")
        if not display_name:
            raise ControlError("display_name 不能为空")
        self._json(
            200,
            self.server.control.backend.rename_kernel(unquote(match["name"]), display_name),
        )

    def _kernel_delete(self, match, query, payload):
        force = str(payload.get("force", query.get("force", ["0"])[0])).lower() in {"1", "true"}
        self._json(
            200,
            self.server.control.backend.remove_kernel(unquote(match["name"]), force=force),
        )

    def _workdirs_post(self, match, query, payload):
        self._json(
            200,
            self.server.control.backend.use_workdir(
                str(payload.get("path") or ""),
                str(payload["kernel"]) if payload.get("kernel") else None,
            ),
        )

    def _upgrades_post(self, match, query, payload):
        targets = payload.get("targets")
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise ControlError("targets 必须是字符串数组")
        profile = str(payload.get("profile") or "web")
        timeout = _float(payload.get("timeout") or dsh_updates.DEFAULT_TIMEOUT)
        self._json(202, self.server.control.backend.upgrade(targets, profile=profile, timeout=timeout))

    def _install_post(self, match, query, payload):
        services = payload.get("services")
        if services is not None and not isinstance(services, list):
            raise ControlError("services 必须是字符串数组")
        icon = payload.get("icon")
        self._json(
            200,
            self.server.control.backend.install(services=services, icon=str(icon) if icon else None),
        )

    def _uninstall_post(self, match, query, payload):
        self._json(200, self.server.control.backend.uninstall())

    def _boot(self, token: str) -> None:
        target = self.server.control.consume_boot(token)
        if target is None:
            self._send(403, b"bootstrap expired", "text/plain; charset=utf-8")
            return
        cookie = f"{COOKIE}={self.server.control.session}; Path=/; HttpOnly; SameSite=Strict"
        self._send(
            303,
            b"",
            "text/plain; charset=utf-8",
            headers={"Location": target, "Set-Cookie": cookie},
        )

    def _static(self, name: str, content_type: str) -> None:
        try:
            body = read_static(name)
        except StaticAssetError:
            self._json(404, {"error": "not found"})
            return
        except OSError:
            self._json(500, {"error": f"缺少前端资源：{name}"})
            return
        self._send(200, body, content_type)

    def _meta(self) -> None:
        control = self.server.control
        self._json(
            200,
            {
                "version": __version__,
                "csrf": control.csrf,
                "port": control.port,
                "pid": os.getpid(),
            },
        )

    # ── 写操作 ────────────────────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802 - http.server 接口
        self._mutate("POST")

    def do_PUT(self) -> None:  # noqa: N802 - http.server 接口
        self._mutate("PUT")

    def do_PATCH(self) -> None:  # noqa: N802 - http.server 接口
        self._mutate("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802 - http.server 接口
        self._mutate("DELETE")

    def _mutate(self, method: str) -> None:
        if not self._auth():
            self._json(403, {"error": "unauthorized"})
            return
        if not self._same_origin() or not self._csrf_ok():
            self._json(403, {"error": "forbidden request"})
            return
        parsed = urlsplit(self.path)
        try:
            payload = self._body()
            self._dispatch(method, parsed.path, parse_qs(parsed.query), payload)
        except Exception as exc:  # noqa: BLE001
            self._error(exc)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise ControlError("Content-Length 无效") from exc
        if length > MAX_BODY:
            raise ControlError("请求体过大", status=413)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlError("请求体不是合法 JSON") from exc
        if not isinstance(payload, dict):
            raise ControlError("请求体必须是对象")
        return payload

    def _action(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "")
        raw_services = payload.get("services")
        if isinstance(raw_services, str):
            services = [raw_services]
        elif isinstance(raw_services, list) and all(isinstance(item, str) for item in raw_services):
            services = list(raw_services)
        else:
            raise ControlError("services 必须是字符串数组")
        if not action or not services:
            raise ControlError("action/services 不能为空")
        force = bool(payload.get("force"))
        backend = self.server.control.backend

        if action in {"start", "stop"} and ("all" in services or len(services) > 1):
            job = self.server.control.jobs.submit(f"{action} all", lambda: backend.batch(action))
        elif len(services) != 1:
            raise ControlError("单个动作只能指定一个服务")
        else:
            service_id = services[0]
            job = self.server.control.jobs.submit(
                f"{action} {service_id}",
                lambda: backend.action(service_id, action, force=force),
            )
        self._json(202, job.as_dict())

    def _quit(self, payload: dict[str, Any]) -> None:
        stop_services = bool(payload.get("stop_services"))
        backend = self.server.control.backend
        self._json(200, {"ok": True})
        timer = threading.Timer(0.25, lambda: _quietly(backend.quit, stop_services=stop_services))
        timer.daemon = True
        timer.start()


class ControlServer:
    """常驻 Agent 内的控制台服务；只绑定 http://127.0.0.1:<随机端口>/。"""

    def __init__(self, backend: ControlBackend) -> None:
        self.backend = backend
        self.session = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(24)
        self._tickets: dict[str, tuple[float, str]] = {}
        self._ticket_lock = threading.Lock()
        self.jobs = JobManager()
        self._closed = False
        httpd = _Httpd(("127.0.0.1", 0), _Handler)
        httpd.control = self
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(target=httpd.serve_forever, name="weblauncher-control", daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def bootstrap_url(self, target: str = "/#/") -> str:
        token = secrets.token_urlsafe(24)
        with self._ticket_lock:
            now = time.monotonic()
            self._tickets = {key: item for key, item in self._tickets.items() if item[0] > now}
            self._tickets[token] = (now + BOOT_TTL, target)
        return f"{self.base_url}/boot/{token}"

    def consume_boot(self, token: str) -> str | None:
        with self._ticket_lock:
            item = self._tickets.pop(token, None)
        if item is None or item[0] <= time.monotonic():
            return None
        target = item[1]
        if not target.startswith("/") or target.startswith("//"):
            return "/#/"
        return target

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(OSError):
            self._httpd.shutdown()
        with contextlib.suppress(OSError):
            self._httpd.server_close()


def _quietly(work: Any, **kwargs: Any) -> None:
    with contextlib.suppress(Exception):
        work(**kwargs)


def _int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return dsh_updates.DEFAULT_TIMEOUT


_LOGIN_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Web 控制台</title><style>
body{font:16px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
     max-width:640px;margin:12vh auto;padding:0 24px;color:#24303f}
code{background:#eef2f7;padding:2px 5px;border-radius:4px}
</style></head><body><h1>控制台需要从启动器打开</h1>
<p>这个页面没有有效的启动器会话。请双击桌面快捷方式，或在终端执行：</p>
<p><code>weblauncher ui</code></p>
<p>控制台只监听本机回环地址，并会在关闭后使旧会话失效。</p>
</body></html>"""
