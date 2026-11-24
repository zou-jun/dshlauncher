"""Web 控制台业务门面：服务视图/动作 + 配置、Jupyter、更新、安装等子服务。"""

from __future__ import annotations

import contextlib
import sys
import threading
from pathlib import Path
from typing import Any

from .. import __version__, doctor, install, logs, memory
from .. import config as config_mod
from ..context import Runtime
from ..controller import ServiceController, ServiceControllerRegistry
from ..services import registry
from ..services.dsh.upgrade import BusyError
from ..status import ServiceStatus
from . import config_store, files
from .errors import ControlError
from .jupyter import JupyterService
from .updates import UpdatesService


class ControlBackend:
    """控制台和 CLI 共用的服务动作集合。

    服务动作仍然走 ``ServiceController`` / ``Supervisor``；这个类只负责
    组合服务视图与各领域子服务，并保护配置/内存的读取与重载。
    """

    def __init__(
        self,
        runtime: Runtime,
        controllers: ServiceControllerRegistry | dict[str, ServiceController],
        *,
        request_quit: Any = None,
    ) -> None:
        self.runtime = runtime
        self.controllers = (
            controllers
            if isinstance(controllers, ServiceControllerRegistry)
            else ServiceControllerRegistry(controllers)
        )
        self._request_quit = request_quit
        self._batch_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self.jupyter = JupyterService(runtime, reload=self._reload)
        self.updates_service = UpdatesService(runtime, exclusive_dsh=self._exclusive_dsh)

    # ── 服务快照 ──────────────────────────────────────────────────────
    def _controller(self, service_id: str) -> ServiceController:
        controller = self.controllers.get(service_id)
        if controller is None:
            raise ControlError(
                self.controllers.errors().get(service_id) or f"未知服务：{service_id}", status=404
            )
        return controller

    def _busy(self, controller: ServiceController) -> bool:
        return controller.busy

    def _snapshot(
        self,
        controller: ServiceController,
        *,
        check_ports: bool = False,
        check_owner: bool = False,
    ) -> dict[str, Any]:
        context = controller.context
        try:
            status: ServiceStatus = controller.service.status(
                check_ports=check_ports,
                check_owner=check_owner,
            )
        except Exception as exc:  # noqa: BLE001 - 状态读取失败也要在 UI 里显示
            return {
                "id": context.service_id,
                "label": context.spec.label,
                "description": context.spec.description,
                "icon": context.spec.icon,
                "tools": [{"slug": slug, "label": label} for slug, label in context.spec.console_tools],
                "running": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        data = status.as_dict()
        data["id"] = context.service_id
        data["description"] = context.spec.description
        data["icon"] = context.spec.icon
        data["open_on_start"] = context.spec.open_on_start
        data["supports_updates"] = context.spec.supports_updates
        data["tools"] = [{"slug": slug, "label": label} for slug, label in context.spec.console_tools]
        data["busy"] = self._busy(controller)
        data["status"] = "running" if status.running else "stopped"
        data["url"] = logs.redact(status.url or "") or None
        data["log"] = str(status.log_path)
        data["data_dir"] = str(status.data_dir)
        data["work_dir"] = str(status.work_dir)
        return data

    def services(self, *, detail: bool = False) -> list[dict[str, Any]]:
        snapshot = self.controllers.snapshot()
        errors = self.controllers.errors()
        rows = [
            self._snapshot(controller, check_ports=True, check_owner=detail)
            for controller in snapshot.values()
        ]
        for service_id, error in errors.items():
            if service_id in snapshot:
                continue
            try:
                spec = registry.spec(service_id)
            except KeyError:
                spec = None
            rows.append(
                {
                    "id": service_id,
                    "label": spec.label if spec is not None else service_id,
                    "description": spec.description if spec is not None else "服务配置不可用",
                    "icon": spec.icon if spec is not None else "",
                    "open_on_start": spec.open_on_start if spec is not None else False,
                    "supports_updates": spec.supports_updates if spec is not None else False,
                    "tools": (
                        [{"slug": slug, "label": label} for slug, label in spec.console_tools]
                        if spec is not None
                        else []
                    ),
                    "running": False,
                    "busy": False,
                    "status": "error",
                    "error": error,
                }
            )
        return rows

    def service(self, service_id: str) -> dict[str, Any]:
        controller = self._controller(service_id)
        data = self._snapshot(controller, check_ports=True, check_owner=True)
        context = controller.context
        data["doctor"] = [
            {"name": label, "value": value} for label, value in doctor.service(self.runtime, service_id)
        ]
        data["settings"] = _public_settings(context.settings)
        return data

    # ── 服务动作 ──────────────────────────────────────────────────────
    def action(
        self,
        service_id: str,
        action: str,
        *,
        force: bool = False,
    ) -> str:
        controller = self._controller(service_id)
        if not controller.try_begin():
            raise ControlError("该服务有操作正在进行，请稍后再试", status=409)
        try:
            if action == "start":
                return controller.start()
            if action == "stop":
                return "已停止" if controller.stop(force=force) else "未运行"
            if action == "restart":
                return controller.restart()
            if action == "open":
                return controller.open_window()
            if action == "open-data":
                return controller.open_data_dir()
            raise ControlError(f"未知动作：{action}", status=400)
        finally:
            controller.end()

    def batch(self, action: str) -> str:
        if action not in {"start", "stop"}:
            raise ControlError(f"未知批量动作：{action}", status=400)
        if not self._batch_lock.acquire(blocking=False):
            raise ControlError("已有批量操作正在进行", status=409)
        ordered = sorted(self.controllers.values(), key=lambda item: item.context.service_id)
        acquired = contextlib.ExitStack()
        try:
            for controller in ordered:
                if not controller.try_begin():
                    raise ControlError("有服务正在执行其它操作，请稍后再试", status=409)
                acquired.callback(controller.end)
            results: list[str] = []
            errors: list[str] = []
            for controller in ordered:
                label = controller.context.spec.label
                try:
                    if action == "start":
                        results.append(f"{label}: {controller.start()}")
                    else:
                        stopped = controller.stop()
                        results.append(f"{label}: {'已停止' if stopped else '未运行'}")
                except Exception as exc:  # noqa: BLE001 - 一个失败不阻断其余
                    errors.append(f"{label}: {type(exc).__name__}: {exc}")
            if errors:
                raise ControlError("；".join(errors), status=500)
            return "；".join(results)
        finally:
            acquired.close()
            self._batch_lock.release()

    def logs(self, service_id: str, *, tail: int = 200) -> dict[str, Any]:
        self._controller(service_id)
        path = self.runtime.paths.service(service_id).log
        text = logs.redact(logs.tail_text(path))
        rows = text.splitlines()
        if tail > 0:
            rows = rows[-tail:]
        return {"service": service_id, "path": str(path), "text": "\n".join(rows), "lines": len(rows)}

    # ── 配置 ──────────────────────────────────────────────────────────
    def config(self) -> dict[str, Any]:
        return config_store.snapshot(self.runtime)

    def _reload(self) -> None:
        """配置/记忆变更后重建上下文；运行中的服务不受影响。"""
        with self._config_lock:
            self.runtime.config = config_mod.load(self.runtime.paths.config)
            self.runtime.memory = memory.load(self.runtime.paths.memory)
            self.updates_service.reset()
            new_controllers: dict[str, ServiceController] = {}
            errors: dict[str, str] = {}
            for service_id in registry.ids():
                try:
                    context = self.runtime.context(service_id)
                except Exception as exc:  # noqa: BLE001 - 配置错误要显示在总览/诊断里
                    errors[service_id] = f"{type(exc).__name__}: {exc}"
                    continue
                new_controllers[service_id] = ServiceController(context)
            self.runtime.errors = errors
            self.controllers.replace(new_controllers, errors=errors)

    def set_config_value(self, key: str, value: Any) -> dict[str, Any]:
        config_store.set_value(self.runtime.paths.config, key, value)
        self._reload()
        return {"key": key, "value": value, "restart_required": True}

    def unset_config_value(self, key: str) -> dict[str, Any]:
        removed = config_store.unset_value(self.runtime.paths.config, key)
        self._reload()
        return {"key": key, "removed": removed, "restart_required": True}

    def save_config_raw(self, raw: str) -> dict[str, Any]:
        config_store.save_raw(self.runtime.paths.config, raw)
        self._reload()
        return {"saved": True, "restart_required": True}

    # ── 诊断 / 安装 / 目录 ────────────────────────────────────────────
    def doctor(self, service_ids: list[str] | None = None) -> dict[str, Any]:
        wanted = registry.split(",".join(service_ids)) if service_ids is not None else registry.ids()
        services = []
        for service_id in wanted:
            try:
                label = self.runtime.context(service_id).spec.label
            except Exception:  # noqa: BLE001 - 配置失败时仍返回该服务的诊断错误行
                label = service_id
            rows = doctor.service(self.runtime, service_id)
            services.append(
                {
                    "id": service_id,
                    "label": label,
                    "rows": [{"name": name, "value": value} for name, value in rows],
                }
            )
        return {
            "general": [{"name": name, "value": value} for name, value in doctor.general(self.runtime)],
            "services": services,
        }

    def install(self, *, services: list[str] | None = None, icon: str | None = None) -> dict[str, Any]:
        if services is None:
            wanted: tuple[str, ...] = registry.ids()
        elif services:
            wanted = registry.split(",".join(services))
        else:
            wanted = ()
        icon_path = Path(icon).expanduser() if icon else None
        created = install.create(icon_path, services=wanted)
        return {"created": [str(path) for path in created]}

    def uninstall(self) -> dict[str, Any]:
        removed = install.remove()
        return {"removed": [str(path) for path in removed]}

    def list_dir(self, value: str, *, include_files: bool = False) -> dict[str, Any]:
        return files.list_dir(value, include_files=include_files)

    # ── Jupyter / 更新（领域子服务） ────────────────────────────────────
    def kernels(self) -> list[dict[str, Any]]:
        return self.jupyter.kernels()

    def add_kernel(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.jupyter.add_kernel(payload)

    def use_kernel(self, name: str) -> dict[str, Any]:
        return self.jupyter.use_kernel(name)

    def rename_kernel(self, name: str, display_name: str) -> dict[str, Any]:
        return self.jupyter.rename_kernel(name, display_name)

    def remove_kernel(self, name: str, *, force: bool = False) -> dict[str, Any]:
        return self.jupyter.remove_kernel(name, force=force)

    def workdirs(self) -> dict[str, Any]:
        return self.jupyter.workdirs()

    def use_workdir(self, value: str, kernel: str | None = None) -> dict[str, Any]:
        return self.jupyter.use_workdir(value, kernel)

    def updates(
        self,
        *,
        refresh: bool = False,
        profile: str = "web",
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return self.updates_service.report(refresh=refresh, profile=profile, timeout=timeout)

    def upgrade(self, targets: list[str], *, profile: str = "web", timeout: float = 30.0) -> dict[str, Any]:
        return self.updates_service.upgrade(targets, profile=profile, timeout=timeout)

    def upgrade_job(self) -> dict[str, Any]:
        return self.updates_service.job()

    def _exclusive_dsh(self, work: Any) -> None:
        controller = self._controller("dsh")
        if not controller.try_begin():
            raise BusyError("dsh 有操作正在进行")
        try:
            work()
        finally:
            controller.end()

    # ── 生命周期 ──────────────────────────────────────────────────────
    def about(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "platform": sys.platform,
            "frozen": bool(getattr(sys, "frozen", False)),
            "data_dir": str(self.runtime.paths.data),
            "config": str(self.runtime.paths.config),
            "memory": str(self.runtime.paths.memory),
            "log": str(self.runtime.paths.launcher_log),
            "upgrades_log": str(self.runtime.paths.upgrades_log),
            "python": sys.executable,
        }

    def quit(self, *, stop_services: bool = False) -> None:
        if self._request_quit is None:
            raise ControlError("当前进程不支持退出控制台", status=400)
        self._request_quit(stop_services=stop_services)


def _public_settings(settings: Any) -> dict[str, Any]:
    """只暴露 UI 需要的设置，不返回 token。"""
    keys = (
        "host",
        "port",
        "work_dir",
        "root_dir",
        "base_url",
        "kernel",
        "node",
        "dsh_bin",
        "jupyter_bin",
        "browser",
        "ozone",
        "start_timeout",
        "dedupe",
        "single_window",
        "remember_per_workdir",
    )
    result: dict[str, Any] = {}
    for key in keys:
        if hasattr(settings, key):
            value = getattr(settings, key)
            result[key] = str(value) if isinstance(value, Path) else value
    return result


__all__ = ["ControlBackend", "ControlError"]
