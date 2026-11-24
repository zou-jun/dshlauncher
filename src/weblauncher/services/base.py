"""托管服务的统一契约。

核心（``supervisor`` / CLI / 托盘）只依赖这里的数据结构与协议，不认具体
服务名；每个服务在 ``services/<id>/`` 下提供自己的适配器。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ServiceSpec:
    id: str
    label: str
    default_port: int
    fallback_ports: tuple[int, ...] = ()
    #: 端口上是同类进程时是否接管（dsh=True；jupyter 不动别人的实例）。
    takeover: bool = False
    #: 没有可信 state 时是否允许按端口扫描并停止（只对 dsh 开启）。
    stop_untracked: bool = False
    supports_updates: bool = False
    open_on_start: bool = False
    description: str = ""
    #: 该服务的控制台子页（slug, label）；路径固定为 /services/<id>/<slug>。
    console_tools: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LaunchPlan:
    argv: list[str]
    env: dict[str, str]
    cwd: Path
    url: str | None = None
    token: str | None = None
    marker: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class ServiceAdapter(Protocol):
    spec: ServiceSpec
    settings: Any

    def prepare(self, *, host: str, port: int) -> LaunchPlan: ...

    def ready(
        self,
        plan: LaunchPlan,
        state: Any,
        *,
        port_open: Callable[[int], bool],
        log_text: Callable[[], str],
    ) -> str | None: ...

    def request_stop(self, state: Any) -> bool: ...

    def owns_process(self, cmdline: str, port: int | None = None) -> bool: ...

    def start_failure(self, log_text: str, port: int) -> str: ...

    def url_from_log(self, log_text: str) -> str | None: ...

    def work_dir(self) -> Path: ...

    def status_extra(self, state: Any) -> dict[str, str]: ...

    def doctor_rows(self) -> list[tuple[str, str]]: ...
