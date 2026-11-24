"""dsh 运行时上下文：Settings + Paths + 平台后端。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ... import platform
from ...paths import Paths
from .service import Service
from .settings import Settings


@dataclass(frozen=True)
class Context:
    settings: Settings
    paths: Paths
    backend: object

    @classmethod
    def create(
        cls,
        settings: Settings,
        *,
        paths_: Paths | None = None,
        backend: object | None = None,
    ) -> Context:
        resolved = paths_ or Paths.current()
        if not settings.profile_explicit:
            settings = replace(settings, profile_dir=resolved.profile)
        return cls(settings, resolved, backend or platform.load())

    def service(self) -> Service:
        return Service(self.settings, paths_=self.paths, backend=self.backend)
