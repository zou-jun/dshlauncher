"""控制台 Jupyter 配置用例：内核与工作目录。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import memory
from ..context import Runtime, ServiceContext
from ..services.jupyter import kernels as jupyter_kernels
from ..services.jupyter import operations as jupyter_operations
from ..services.jupyter import workdirs as jupyter_workdirs
from .errors import ControlError


class JupyterService:
    def __init__(self, runtime: Runtime, *, reload: Callable[[], None]) -> None:
        self.runtime = runtime
        self._reload = reload

    def _context(self) -> ServiceContext:
        try:
            return self.runtime.context("jupyter")
        except Exception as exc:  # noqa: BLE001 - 缺少 jupyter 时返回可读错误
            raise ControlError(f"Jupyter 不可用：{type(exc).__name__}: {exc}") from exc

    def kernels(self) -> list[dict[str, Any]]:
        context = self._context()
        install = context.adapter.install
        specs = jupyter_kernels.list_kernels(install, self.runtime.memory)
        default = getattr(context.settings, "kernel", None)
        rows = []
        for spec in specs:
            data = spec.as_dict()
            data["default"] = spec.name == default
            rows.append(data)
        return rows

    def add_kernel(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._context()
        try:
            spec = jupyter_operations.add_kernel(
                context.adapter.install,
                self.runtime.memory,
                directory=payload.get("dir"),
                python=payload.get("python"),
                name=str(payload.get("name") or "") or None,
                display_name=str(payload.get("display_name") or "") or None,
                replace=bool(payload.get("replace")),
                install_dependency=bool(payload.get("install_ipykernel")),
            )
        except (jupyter_operations.JupyterOperationError, jupyter_kernels.KernelError) as exc:
            raise ControlError(str(exc)) from exc
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return spec.as_dict()

    def use_kernel(self, name: str) -> dict[str, Any]:
        context = self._context()
        try:
            spec = jupyter_operations.select_kernel(
                context.adapter.install,
                self.runtime.memory,
                name,
                workdir=context.settings.root_dir,
            )
        except (jupyter_operations.JupyterOperationError, jupyter_kernels.KernelError) as exc:
            raise ControlError(str(exc)) from exc
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return {"kernel": spec.name, "restart_required": True}

    def rename_kernel(self, name: str, display_name: str) -> dict[str, Any]:
        context = self._context()
        try:
            spec = jupyter_kernels.require_found(context.adapter.install, self.runtime.memory, name)
            renamed = jupyter_kernels.rename_kernel(spec, display_name)
        except jupyter_kernels.KernelError as exc:
            raise ControlError(str(exc)) from exc
        return renamed.as_dict()

    def remove_kernel(self, name: str, *, force: bool = False) -> dict[str, Any]:
        context = self._context()
        try:
            spec = jupyter_operations.remove_kernel(
                context.adapter.install,
                self.runtime.memory,
                name,
                force=force,
            )
        except (jupyter_operations.JupyterOperationError, jupyter_kernels.KernelError) as exc:
            raise ControlError(str(exc)) from exc
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return {"removed": spec.name}

    def workdirs(self) -> dict[str, Any]:
        context = self._context()
        values = jupyter_workdirs.recent(self.runtime.memory)
        current = memory.get(self.runtime.memory, "jupyter", "workdir", None)
        return {
            "current": str(current) if current else str(context.settings.root_dir),
            "items": [
                {"path": str(path), "exists": path.is_dir(), "current": str(path) == str(current)}
                for path in values
            ],
        }

    def use_workdir(self, value: str, kernel: str | None = None) -> dict[str, Any]:
        context = self._context()
        try:
            workdir = jupyter_operations.select_workdir(
                context.adapter.install if kernel else None,
                self.runtime.memory,
                value,
                kernel=kernel,
            )
        except (
            jupyter_operations.JupyterOperationError,
            jupyter_kernels.KernelError,
            jupyter_workdirs.WorkdirError,
        ) as exc:
            raise ControlError(str(exc)) from exc
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return {"path": str(workdir), "restart_required": True}


__all__ = ["JupyterService"]
