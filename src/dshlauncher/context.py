"""运行时上下文：Settings + Paths + 平台后端，启动时创建一次并向下传递。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import ModuleType

from . import paths, platform
from .service import Service
from .settings import Settings


@dataclass(frozen=True)
class Context:
    settings: Settings
    paths: paths.Paths
    backend: ModuleType

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        paths_: paths.Paths | None = None,
        backend: ModuleType | None = None,
    ) -> Context:
        resolved = paths_ or paths.Paths.current()
        if not settings.profile_explicit:
            # 浏览器 profile 跟着运行时的数据目录走，而不是模块级默认路径。
            settings = replace(settings, profile_dir=resolved.profile)
        return cls(settings, resolved, backend or platform.load())

    def service(self) -> Service:
        return Service(self.settings, paths_=self.paths, backend=self.backend)
