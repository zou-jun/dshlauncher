"""dsh web 适配器。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ... import paths, ports
from ...paths import Paths
from ...services.base import LaunchPlan, ServiceSpec
from . import discovery, parse
from .settings import Settings

WEB_PROFILE = "web"


class DshAdapter:
    spec = ServiceSpec(
        id="dsh",
        label="dsh web",
        description="DeepSeek Harness web 服务",
        default_port=3080,
        fallback_ports=ports.FALLBACK_PORTS,
        takeover=True,
        use_splash=True,
        stop_untracked=True,
        supports_updates=True,
        auto_start=True,
        open_on_start=True,
    )

    def __init__(self, settings: Settings, paths_: Paths | None = None) -> None:
        self.settings = settings
        self.paths = paths_ or Paths.current()

    def prepare(self, *, host: str, port: int) -> LaunchPlan:
        node = discovery.node_exe(self.settings.node)
        bin_js = discovery.dsh_bin(self.settings.dsh_bin)
        argv = [
            str(node),
            str(bin_js),
            WEB_PROFILE,
            "--no-open",
            "--host",
            host,
            "--port",
            str(port),
        ]
        return LaunchPlan(
            argv=argv,
            env=paths.child_env(),
            cwd=self.settings.work_dir,
            marker="\n[launcher] start port={port} at={at}\n",
        )

    def ready(self, plan, state, *, port_open, log_text) -> str | None:  # noqa: ANN001
        url = parse.parse_url(log_text())
        if url and (state.port == 0 or port_open(state.port)):
            return url
        return None

    def request_stop(self, state) -> bool:  # noqa: ANN001
        return False

    def owns_process(self, cmdline: str, port: int | None = None) -> bool:
        if self.settings.dsh_bin is not None:
            configured = str(self.settings.dsh_bin).replace("\\", "/")
            if configured and configured in cmdline.replace("\\", "/"):
                return True
        return parse.is_dsh_cmdline(cmdline)

    def start_failure(self, log_text: str, port: int) -> str:
        reason = parse.startup_failure(log_text)
        hint = ""
        if "EACCES" in reason:
            hint = ports.reserved_message(self.settings.host, port)
        elif "EADDRINUSE" in reason:
            hint = f"端口 {port} 已被其它进程占用"
        return (reason or "（日志里没有可读的失败信息）") + (f"\n{hint}" if hint else "")

    def url_from_log(self, log_text: str) -> str | None:
        return parse.parse_url(log_text)

    def work_dir(self) -> Path:
        return self.settings.work_dir

    def status_extra(self, state) -> dict[str, str]:  # noqa: ANN001
        extra = {"profile": WEB_PROFILE}
        try:
            version = _installed_version(discovery.dsh_bin(self.settings.dsh_bin))
        except Exception:  # noqa: BLE001 - 状态展示不能因发现失败而中断
            version = ""
        if version:
            extra["dsh"] = version
        return extra

    def doctor_rows(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for label, resolver in (
            ("node", lambda: str(discovery.node_exe(self.settings.node))),
            ("dsh", lambda: str(discovery.dsh_bin(self.settings.dsh_bin))),
        ):
            try:
                rows.append((label, resolver()))
            except Exception as exc:  # noqa: BLE001 - doctor 逐项展示失败
                rows.append((label, f"不可用: {exc}"))
        return rows


def _installed_version(bin_js: Path) -> str:
    candidate = bin_js.resolve()
    for parent in (candidate.parent, candidate.parent.parent, candidate.parent.parent.parent):
        try:
            data = json.loads((parent / "package.json").read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("name") and data.get("version"):
            return str(data["version"])
    return ""


def marker_now() -> str:
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"
