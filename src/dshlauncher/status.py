"""服务状态快照与三种展示形态（短标签 / tooltip / 完整详情 / JSON）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ServiceStatus:
    running: bool
    pid: int | None
    host: str
    port: int
    listening: bool
    url: str | None
    work_dir: Path
    data_dir: Path
    log_path: Path
    owner: str | None = None

    def short(self) -> str:
        return "运行中" if self.running else "未运行"

    def tooltip(self) -> str:
        if not self.running:
            return "未运行"
        return f"运行中 · pid={self.pid} · {self.host}:{self.port}"

    def full(self, *, english: bool = False) -> str:
        pid = self.pid if self.pid is not None else "-"
        warning = not self.running and self.listening
        if english:
            lines = [
                f"Service : {'running' if self.running else 'stopped'}",
                f"PID     : {pid}",
                f"Port    : {self.host}:{self.port} ({'LISTENING' if self.listening else 'closed'})",
                f"URL     : {self.url or '-'}",
                f"Workdir : {self.work_dir}",
                f"Data    : {self.data_dir}",
                f"Log     : {self.log_path}",
            ]
            if warning:
                lines.append(f"Warning : port held by -> {self.owner or 'unknown'}")
            return "\n".join(lines)

        lines = [
            f"服务: {'运行中' if self.running else '未运行'}",
            f"PID : {pid}",
            f"端口: {self.host}:{self.port} ({'LISTENING' if self.listening else 'closed'})",
            f"URL : {self.url or '-'}",
            f"工作目录: {self.work_dir}",
            f"数据目录: {self.data_dir}",
            f"日志: {self.log_path}",
        ]
        if warning:
            lines.append(f"注意: 端口被外部进程占用 -> {self.owner or '未知'}")
        return "\n".join(lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "pid": self.pid,
            "host": self.host,
            "port": self.port,
            "listening": self.listening,
            "url": self.url,
            "owner": self.owner,
            "work_dir": str(self.work_dir),
            "data_dir": str(self.data_dir),
            "log": str(self.log_path),
        }
