"""托盘动作与并发状态；不依赖 pystray，便于单测。"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from .. import actions, service
from ..context import Context


def status_text(service_: service.Service) -> str:
    """tooltip 用的完整短状态；不探测端口。"""
    return service_.status(check_ports=False).tooltip()


def state_text(service_: service.Service) -> str:
    """菜单里的短状态；详情由「服务状态」弹窗提供。"""
    return service_.status(check_ports=False).short()


class TrayController:
    def __init__(self, context: Context) -> None:
        self.context = context
        self.settings = context.settings
        self.paths = context.paths
        self.service = context.service()
        self._busy = threading.Lock()
        self._stopping = threading.Event()
        self._starting = threading.Event()

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def mark_stopping(self) -> None:
        self._stopping.set()

    def try_begin(self) -> bool:
        return self._busy.acquire(blocking=False)

    def end(self) -> None:
        self._busy.release()

    def run_exclusive(self, work: Callable[[], Any]) -> Any:
        with self._busy:
            return work()

    def status_short(self) -> str:
        return "启动中…" if self._starting.is_set() else state_text(self.service)

    def status_tooltip(self) -> str:
        return "正在启动服务…" if self._starting.is_set() else status_text(self.service)

    def open_window(self) -> str:
        self._starting.set()
        try:
            return actions.open_dsh(self.context)
        finally:
            self._starting.clear()

    def restart(self) -> str:
        return actions.restart(self.context)

    def stop(self) -> bool:
        return self.service.stop()

    def describe(self) -> str:
        return self.service.describe()

    def open_log(self) -> str:
        self.paths.ensure()
        self.paths.log.touch(exist_ok=True)
        self.context.backend.open_path(self.paths.log)
        return f"已打开 {self.paths.log}"

    def open_data_dir(self) -> str:
        self.context.backend.open_path(self.paths.ensure())
        return f"已打开 {self.paths.data}"
