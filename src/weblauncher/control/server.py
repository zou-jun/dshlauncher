"""控制台 HTTP 服务：一次性入口、Cookie 会话、JSON API 与静态 SPA。"""

from __future__ import annotations

import collections
import contextlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .. import __version__
from ..services.dsh import updates as dsh_updates
from .backend import ControlBackend, ControlError

COOKIE = "weblauncher_session"
BOOT_TTL = 120.0
MAX_BODY = 1024 * 1024
STATIC = Path(__file__).resolve().parent.parent / "webui" / "static"


@dataclass
class Job:
    id: str
    label: str
    status: str = "running"
    result: Any = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: collections.OrderedDict[str, Job] = collections.OrderedDict()

    def submit(self, label: str, work: Any) -> Job:
        job = Job(id=secrets.token_hex(8), label=label)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > 50:
                self._jobs.popitem(last=False)
        thread = threading.Thread(
            target=self._run,
            args=(job, work),
            name=f"control-{job.id}",
            daemon=True,
        )
        thread.start()
        return job

    def _run(self, job: Job, work: Any) -> None:
        try:
            job.result = work()
        except Exception as exc:  # noqa: BLE001 - 任务失败必须回给页面
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"
        else:
            job.status = "succeeded"
        finally:
            job.finished_at = time.time()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.as_dict() for job in reversed(self._jobs.values())][:20]


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

    # ── GET ───────────────────────────────────────────────────────────
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
            if path in {"/", "/index.html"}:
                self._static("index.html", "text/html; charset=utf-8")
            elif path == "/app.js":
                self._static("app.js", "text/javascript; charset=utf-8")
            elif path == "/styles.css":
                self._static("styles.css", "text/css; charset=utf-8")
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            elif path == "/api/meta":
                self._meta()
            elif path == "/api/services":
                self._json(200, {"services": self.server.control.backend.services()})
            elif path.startswith("/api/services/") and path.endswith("/logs"):
                service_id = unquote(path[len("/api/services/") : -len("/logs")].strip("/"))
                tail = _int(parse_qs(parsed.query).get("tail", ["200"])[0], 200)
                self._json(200, self.server.control.backend.logs(service_id, tail=tail))
            elif path.startswith("/api/services/"):
                service_id = unquote(path.removeprefix("/api/services/").strip("/"))
                self._json(200, self.server.control.backend.service(service_id))
            elif path == "/api/jobs":
                self._json(200, {"jobs": self.server.control.jobs.recent()})
            elif path.startswith("/api/jobs/"):
                job = self.server.control.jobs.get(path.removeprefix("/api/jobs/"))
                if job is None:
                    self._json(404, {"error": "任务不存在"})
                else:
                    self._json(200, job.as_dict())
            elif path == "/api/doctor":
                query = parse_qs(parsed.query)
                services = query.get("service", [None])[0]
                wanted = [item for item in (services or "").split(",") if item] or None
                self._json(200, {"rows": self.server.control.backend.doctor(wanted)})
            elif path == "/api/config":
                self._json(200, self.server.control.backend.config())
            elif path == "/api/jupyter/kernels":
                self._json(200, {"kernels": self.server.control.backend.kernels()})
            elif path.startswith("/api/jupyter/kernels/"):
                name = unquote(path.removeprefix("/api/jupyter/kernels/").strip("/"))
                kernels = self.server.control.backend.kernels()
                found = next((row for row in kernels if row.get("name") == name), None)
                if found is None:
                    self._json(404, {"error": f"内核不存在：{name}"})
                else:
                    self._json(200, found)
            elif path == "/api/jupyter/workdirs":
                self._json(200, self.server.control.backend.workdirs())
            elif path == "/api/updates":
                query = parse_qs(parsed.query)
                profile = query.get("profile", ["web"])[0]
                timeout = _float(query.get("timeout", [str(dsh_updates.DEFAULT_TIMEOUT)])[0])
                refresh = query.get("refresh", ["0"])[0] == "1"
                self._json(
                    200,
                    self.server.control.backend.updates(
                        refresh=refresh,
                        profile=profile,
                        timeout=timeout,
                    ),
                )
            elif path == "/api/upgrade-job":
                self._json(200, self.server.control.backend.upgrade_job())
            elif path == "/api/fs":
                query = parse_qs(parsed.query)
                value = query.get("path", [""])[0]
                include_files = query.get("files", ["0"])[0] == "1"
                self._json(200, self.server.control.backend.list_dir(value, include_files=include_files))
            elif path == "/api/about":
                self._json(200, self.server.control.backend.about())
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001 - API 必须把具体失败显示在页面
            self._error(exc)

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
        path = STATIC / name
        try:
            body = path.read_bytes()
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
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            payload = self._body()
            if path == "/api/actions":
                self._action(payload)
            elif path == "/api/agent/quit":
                self._quit(payload)
            elif path == "/api/config":
                raw = payload.get("raw")
                if not isinstance(raw, str):
                    raise ControlError("raw 必须是字符串")
                self._json(200, self.server.control.backend.save_config_raw(raw))
            elif path == "/api/config/value":
                key = str(payload.get("key") or query.get("key", [""])[0])
                if not key:
                    raise ControlError("缺少配置键")
                if method == "DELETE":
                    self._json(200, self.server.control.backend.unset_config_value(key))
                else:
                    if "value" not in payload:
                        raise ControlError("缺少 value")
                    self._json(200, self.server.control.backend.set_config_value(key, payload["value"]))
            elif path == "/api/jupyter/kernels" and method == "POST":
                self._json(200, self.server.control.backend.add_kernel(payload))
            elif path.startswith("/api/jupyter/kernels/") and path.endswith("/use"):
                name = unquote(path.removeprefix("/api/jupyter/kernels/")[: -len("/use")].strip("/"))
                self._json(200, self.server.control.backend.use_kernel(name))
            elif path.startswith("/api/jupyter/kernels/") and method == "PATCH":
                name = unquote(path.removeprefix("/api/jupyter/kernels/").strip("/"))
                display_name = str(payload.get("display_name") or "")
                if not display_name:
                    raise ControlError("display_name 不能为空")
                self._json(200, self.server.control.backend.rename_kernel(name, display_name))
            elif path.startswith("/api/jupyter/kernels/") and method == "DELETE":
                name = unquote(path.removeprefix("/api/jupyter/kernels/").strip("/"))
                force = str(payload.get("force", query.get("force", ["0"])[0])).lower() in {"1", "true"}
                self._json(200, self.server.control.backend.remove_kernel(name, force=force))
            elif path == "/api/jupyter/workdirs" and method == "POST":
                self._json(
                    200,
                    self.server.control.backend.use_workdir(
                        str(payload.get("path") or ""),
                        str(payload["kernel"]) if payload.get("kernel") else None,
                    ),
                )
            elif path == "/api/upgrades" and method == "POST":
                targets = payload.get("targets")
                if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
                    raise ControlError("targets 必须是字符串数组")
                profile = str(payload.get("profile") or "web")
                timeout = _float(payload.get("timeout") or dsh_updates.DEFAULT_TIMEOUT)
                self._json(
                    202, self.server.control.backend.upgrade(targets, profile=profile, timeout=timeout)
                )
            elif path == "/api/install" and method == "POST":
                services = payload.get("services")
                if services is not None and not isinstance(services, list):
                    raise ControlError("services 必须是字符串数组")
                icon = payload.get("icon")
                self._json(
                    200,
                    self.server.control.backend.install(
                        services=services,
                        icon=str(icon) if icon else None,
                    ),
                )
            elif path == "/api/uninstall" and method == "POST":
                self._json(200, self.server.control.backend.uninstall())
            else:
                self._json(404, {"error": "not found"})
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
