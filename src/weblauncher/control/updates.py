"""控制台 dsh 更新检查与升级任务。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..context import Runtime
from ..services.dsh import updates as dsh_updates
from ..services.dsh.upgrade import BusyError, UpgradeError, UpgradeManager
from .errors import ControlError


@dataclass(frozen=True)
class _CachedReport:
    at: float
    profile: str
    timeout: float
    report: dsh_updates.UpdateReport


class UpdatesService:
    def __init__(
        self,
        runtime: Runtime,
        *,
        exclusive_dsh: Callable[[Callable[[], Any]], None],
    ) -> None:
        self.runtime = runtime
        self._exclusive_dsh = exclusive_dsh
        self._lock = threading.Lock()
        self._cached: _CachedReport | None = None
        self._upgrade: UpgradeManager | None = None

    def reset(self) -> None:
        with self._lock:
            self._cached = None
            self._upgrade = None

    def report(
        self,
        *,
        refresh: bool = False,
        profile: str = "web",
        timeout: float = dsh_updates.DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        context = self.runtime.context("dsh")
        with self._lock:
            cached = self._cached
            fresh = (
                cached is not None
                and not refresh
                and cached.profile == profile
                and cached.timeout == timeout
                and time.monotonic() - cached.at < 20.0
            )
            report = cached.report if fresh and cached is not None else None
            if report is None:
                report = dsh_updates.check(context.settings, profile=profile, timeout=timeout)
                self._cached = _CachedReport(time.monotonic(), profile, timeout, report)
            return report.as_dict()

    def _manager(self) -> UpgradeManager:
        if self._upgrade is None:
            context = self.runtime.context("dsh")
            self._upgrade = UpgradeManager(context, exclusive=self._exclusive_dsh)
        return self._upgrade

    def upgrade(
        self,
        targets: list[str],
        *,
        profile: str = "web",
        timeout: float = dsh_updates.DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        if not isinstance(targets, list) or not targets or not all(isinstance(item, str) for item in targets):
            raise ControlError("targets 必须是字符串数组")
        report = dsh_updates.check(
            self.runtime.context("dsh").settings,
            profile=profile,
            timeout=timeout,
        )
        with self._lock:
            self._cached = _CachedReport(time.monotonic(), profile, timeout, report)
        try:
            return self._manager().start(targets, report)
        except BusyError as exc:
            raise ControlError(str(exc), status=409) from exc
        except UpgradeError as exc:
            raise ControlError(str(exc), status=400) from exc

    def job(self) -> dict[str, Any]:
        manager = self._manager()
        job = manager.job
        return job.as_dict() if job is not None else {"status": "idle"}


__all__ = ["UpdatesService"]
