"""服务动作协调器：供 CLI、Web 控制台和托盘共用，不依赖 pystray。"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import Any

from . import actions
from .context import ServiceContext
from .supervisor import Supervisor


def status_text(service_: Supervisor) -> str:
    """tooltip 用的完整短状态；不探测端口。"""
    return service_.status(check_ports=False).tooltip()


def state_text(service_: Supervisor) -> str:
    """菜单里的短状态；详情由「服务状态」弹窗提供。"""
    return service_.status(check_ports=False).short()


class ServiceController:
    """单个服务的动作互斥与窗口动作。

    跨进程的 start/stop/restart 互斥由 ``Supervisor`` 的 ``service.lock``
    负责；这一层只保护当前 Agent 内的动作/UI 状态。
    """

    def __init__(self, context: ServiceContext) -> None:
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

    @property
    def busy(self) -> bool:
        """只读探测，不抢占动作锁。"""
        return self._busy.locked()

    def mark_stopping(self) -> None:
        self._stopping.set()

    def try_begin(self) -> bool:
        return self._busy.acquire(blocking=False)

    def end(self) -> None:
        self._busy.release()

    def run_exclusive(self, work: Callable[[], Any]) -> Any:
        with self._busy:
            return work()

    @contextlib.contextmanager
    def held(self):
        """阻塞等待并持有动作锁；用于“停止全部”等待启动完成。"""
        with self._busy:
            yield

    def status_short(self) -> str:
        return "启动中" if self._starting.is_set() else state_text(self.service)

    def status_tooltip(self) -> str:
        return "正在启动服务…" if self._starting.is_set() else status_text(self.service)

    def start(self) -> str:
        self._starting.set()
        try:
            state = self.service.start()
            return f"pid={state.pid}"
        finally:
            self._starting.clear()

    def open_window(self) -> str:
        self._starting.set()
        try:
            return actions.open_service(self.context)
        finally:
            self._starting.clear()

    def restart(self) -> str:
        return actions.restart(self.context)

    def stop(self, *, force: bool = False) -> bool:
        return self.service.stop(force=force)

    def describe(self) -> str:
        return self.service.describe()

    def open_data_dir(self) -> str:
        self.context.backend.open_path(self.paths.ensure())
        return f"已打开 {self.paths.data}"


class ServiceControllerRegistry:
    """线程安全的服务控制器集合；配置重载时整体替换，不原地清空。"""

    def __init__(
        self,
        controllers: dict[str, ServiceController] | None = None,
        *,
        errors: dict[str, str] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, ServiceController] = dict(controllers or {})
        self._errors: dict[str, str] = dict(errors or {})

    def get(self, service_id: str) -> ServiceController | None:
        with self._lock:
            return self._items.get(service_id)

    def snapshot(self) -> dict[str, ServiceController]:
        with self._lock:
            return dict(self._items)

    def values(self) -> tuple[ServiceController, ...]:
        with self._lock:
            return tuple(self._items.values())

    def ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._items)

    def errors(self) -> dict[str, str]:
        with self._lock:
            return dict(self._errors)

    def replace(
        self,
        controllers: dict[str, ServiceController],
        *,
        errors: dict[str, str] | None = None,
    ) -> None:
        with self._lock:
            self._items = dict(controllers)
            self._errors = dict(errors or {})

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def __contains__(self, service_id: object) -> bool:
        with self._lock:
            return service_id in self._items
