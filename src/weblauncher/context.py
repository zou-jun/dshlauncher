"""运行时上下文：全局路径/配置/记忆 + 单个服务的 settings/adapter。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import config as config_mod
from . import memory as memory_mod
from . import platform
from . import state as state_mod
from .paths import Paths
from .services.base import ServiceAdapter
from .supervisor import Supervisor


@dataclass(frozen=True)
class ServiceContext:
    runtime: Runtime
    service_id: str
    settings: Any
    adapter: ServiceAdapter

    @property
    def paths(self) -> Paths:
        return self.runtime.paths

    @property
    def backend(self) -> Any:
        return self.runtime.backend

    @property
    def spec(self):
        return self.adapter.spec

    def service(self) -> Supervisor:
        return Supervisor(
            self.adapter,
            paths_=self.runtime.paths,
            backend=self.runtime.backend,
            other_ports=lambda: self.runtime.other_ports(self.service_id),
        )


@dataclass
class Runtime:
    paths: Paths
    config: config_mod.Config
    memory: dict[str, Any]
    backend: Any
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        paths_: Paths | None = None,
        backend: Any | None = None,
        config: config_mod.Config | None = None,
        memory: dict[str, Any] | None = None,
        migrate: bool = True,
    ) -> Runtime:
        resolved = paths_ or Paths.current()
        if migrate:
            resolved.migrate_legacy()
        return cls(
            paths=resolved,
            config=config or config_mod.load(resolved.config),
            memory=memory if memory is not None else memory_mod.load(resolved.memory),
            backend=backend or platform.load(),
        )

    def context(self, service_id: str, cli: dict[str, Any] | None = None) -> ServiceContext:
        from .services import registry

        return registry.build(self, service_id, cli=cli)

    def contexts(
        self,
        service_ids: tuple[str, ...] | list[str] | None = None,
        cli: dict[str, Any] | None = None,
    ) -> list[ServiceContext]:
        from .services import registry

        wanted = tuple(service_ids) if service_ids is not None else registry.ids()
        contexts: list[ServiceContext] = []
        self.errors = {}
        for service_id in wanted:
            try:
                contexts.append(self.context(service_id, cli))
            except Exception as exc:  # noqa: BLE001 - 单个服务不可用不能拖垮托盘/批量命令
                self.errors[service_id] = f"{type(exc).__name__}: {exc}"
        return contexts

    def other_ports(self, service_id: str) -> set[int]:
        """其它服务配置/上次使用过的端口，自动选端口时排除。"""
        from .services import registry

        ports: set[int] = set()
        for other in registry.ids():
            if other == service_id:
                continue
            section = self.config.section(other)
            configured = section.get("port", self.config.raw.get("port"))
            if isinstance(configured, int):
                ports.add(configured)
            state = state_mod.read_state(self.paths.service(other).state)
            if state is not None and state.port:
                ports.add(state.port)
        return ports
