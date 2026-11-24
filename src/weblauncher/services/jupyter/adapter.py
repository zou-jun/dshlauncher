"""Jupyter Lab 适配器：随机 token、HTTP 就绪与优雅关闭。"""

from __future__ import annotations

import json
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path

from ... import paths
from ...services.base import LaunchPlan, ServiceSpec
from .discovery import Install
from .settings import Settings

#: 端口冲突时不接管、自动换端口；启动快，不需要过场页。
FALLBACK_PORTS = (8889, 8890, 8891, 18888, 18889)


def _url_host(host: str) -> str:
    if host in {"0.0.0.0", ""}:
        return "127.0.0.1"
    if host == "::":
        return "[::1]"
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


class JupyterAdapter:
    spec = ServiceSpec(
        id="jupyter",
        label="Jupyter Lab",
        description="uv tool 安装的 Jupyter Lab",
        default_port=8888,
        fallback_ports=FALLBACK_PORTS,
        takeover=False,
        use_splash=False,
        stop_untracked=False,
        supports_updates=False,
        auto_start=False,
        open_on_start=False,
    )

    def __init__(self, settings: Settings, install: Install, memory: dict | None = None) -> None:
        self.settings = settings
        self.install = install
        self.memory = memory or {}

    # ── 启动 ──────────────────────────────────────────────────────────
    def prepare(self, *, host: str, port: int) -> LaunchPlan:
        if not self.settings.root_dir.is_dir():
            raise RuntimeError(
                f"Jupyter 工作目录不存在：{self.settings.root_dir}\n用 `jupyter workdir use <目录>` 重新选择"
            )
        token = self.settings.token or secrets.token_hex(24)
        base = self.settings.base_url
        url = f"http://{_url_host(host)}:{port}{base}lab?token={token}"
        argv = [
            *self.install.argv,
            "--no-browser",
            f"--ServerApp.ip={host}",
            f"--ServerApp.port={port}",
            "--ServerApp.port_retries=0",
            f"--ServerApp.root_dir={self.settings.root_dir}",
            f"--ServerApp.base_url={base}",
        ]
        if self.settings.kernel:
            argv.append(f"--MappingKernelManager.default_kernel_name={self.settings.kernel}")
        env = paths.child_env()
        env["JUPYTER_TOKEN"] = token
        env["PYTHONUNBUFFERED"] = "1"
        return LaunchPlan(
            argv=argv,
            env=env,
            cwd=self.settings.root_dir,
            url=url,
            token=token,
            marker="\n[launcher] start port={port} at={at} root=" + str(self.settings.root_dir) + "\n",
            extra={"root_dir": str(self.settings.root_dir), "kernel": self.settings.kernel or ""},
        )

    def ready(self, plan, state, *, port_open, log_text) -> str | None:  # noqa: ANN001
        port = state.port
        url = plan.url
        if not port:
            # --port 0：真实端口只出现在 Jupyter 的启动日志里（token 已打码）。
            match = re.search(r"http://[^\s:]+:(\d+)/", log_text())
            if match is None:
                return None
            port = int(match.group(1))
            state.port = port
            if url:
                url = re.sub(r":0(?=/|\?)", f":{port}", url, count=1)
        if not port_open(port):
            return None
        request = urllib.request.Request(
            self.status_url(port),
            headers={"Authorization": f"token {plan.token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return url if response.status == 200 else None
        except (urllib.error.URLError, TimeoutError, OSError):
            return None

    def request_stop(self, state) -> bool:  # noqa: ANN001
        request = urllib.request.Request(
            self.shutdown_url(state.port),
            headers={"Authorization": f"token {state.token}"},
            data=b"",
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status in {200, 204}
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    # ── 判定与展示 ────────────────────────────────────────────────────
    def owns_process(self, cmdline: str, port: int | None = None) -> bool:
        lowered = cmdline.lower().replace("\\", "/")
        if "jupyter-lab" not in lowered and "jupyterlab" not in lowered and "jupyter_server" not in lowered:
            return False
        if port is None:
            return True
        patterns = (
            rf"--serverapp\.port={port}\b",
            rf"--port={port}\b",
            rf"--port\s+{port}\b",
        )
        return any(re.search(pattern, lowered) for pattern in patterns)

    def start_failure(self, log_text: str, port: int) -> str:
        rows = [row.strip() for row in (log_text or "").splitlines() if row.strip()]
        tail = "\n".join(rows[-12:])
        hints: list[str] = []
        if re.search(r"address already in use|errno 98|winerror 10048", tail, re.IGNORECASE):
            hints.append(f"端口 {port} 已被占用。换端口：--port {FALLBACK_PORTS[0]}")
        if "no module named" in tail.lower():
            hints.append("Jupyter 环境不完整：重新执行 `uv tool install jupyterlab --force`")
        return tail + ("\n" + "\n".join(hints) if hints else "")

    def url_from_log(self, log_text: str) -> str | None:
        # 4.6+ 日志把 token 打码成 ?token=...，不能从日志恢复。
        return None

    def work_dir(self) -> Path:
        return self.settings.root_dir

    def status_extra(self, state) -> dict[str, str]:  # noqa: ANN001
        extra = {"root_dir": str(self.settings.root_dir)}
        if self.settings.kernel:
            extra["kernel"] = self.settings.kernel
        extra["base_url"] = self.settings.base_url
        return extra

    def doctor_rows(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = [("jupyter-lab", str(self.install.lab or self.install.argv[0]))]
        if self.install.version:
            rows.append(("jupyter 版本", self.install.version))
        env_text = str(self.install.env) if self.install.env else "未识别（仅用 PATH shim）"
        rows.append(("jupyter 环境", env_text))
        root_text = (
            str(self.settings.root_dir)
            if self.settings.root_dir.is_dir()
            else f"{self.settings.root_dir}（不存在）"
        )
        rows.append(("root_dir", root_text))
        rows.append(("默认内核", self.settings.kernel or "（Jupyter 默认）"))
        return rows

    # ── URL ───────────────────────────────────────────────────────────
    def status_url(self, port: int) -> str:
        return f"http://{_url_host(self.settings.host)}:{port}{self.settings.base_url}api/status"

    def shutdown_url(self, port: int) -> str:
        return f"http://{_url_host(self.settings.host)}:{port}{self.settings.base_url}api/shutdown"


def kernel_names(install: Install, memory: dict) -> list[str]:
    """给 doctor/CLI 用的内核名称列表；导入放这里避免顶层循环。"""
    from . import kernels

    return [kernel.name for kernel in kernels.list_kernels(install, memory)]


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
