"""Web 控制台的业务后端：把 CLI 动作整理成可被 HTTP 调用的数据结构。"""

from __future__ import annotations

import contextlib
import datetime as dt
import os
import sys
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import __version__, doctor, install, logs, memory
from .. import config as config_mod
from .. import paths as paths_mod
from ..context import Runtime, ServiceContext
from ..services import registry
from ..services.dsh import updates as dsh_updates
from ..services.dsh.upgrade import BusyError, UpgradeError, UpgradeManager
from ..services.jupyter import kernels as jupyter_kernels
from ..services.jupyter import workdirs as jupyter_workdirs
from ..status import ServiceStatus
from ..tray.controller import TrayController


class ControlError(RuntimeError):
    """带 HTTP 状态码的业务错误。"""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


CONFIG_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "key": "launcher.start_timeout",
        "label": "启动超时（秒）",
        "type": "number",
        "section": "launcher",
        "help": "等待服务就绪的最长时间",
    },
    {
        "key": "launcher.tray_exit_stops_services",
        "label": "退出时停止服务",
        "type": "boolean",
        "section": "launcher",
        "help": "Ctrl+C / 退出控制台时是否停止托管服务",
    },
    {
        "key": "ui.browser",
        "label": "浏览器",
        "type": "string",
        "section": "ui",
        "help": "chrome / edge / chromium / brave 或路径",
    },
    {
        "key": "ui.ozone",
        "label": "Linux 显示后端",
        "type": "select",
        "section": "ui",
        "choices": list(config_mod.OZONE_MODES),
    },
    {"key": "ui.dedupe", "label": "浏览器窗口去重", "type": "boolean", "section": "ui"},
    {"key": "ui.window.width_ratio", "label": "窗口宽度比例", "type": "number", "section": "ui.window"},
    {"key": "ui.window.height_ratio", "label": "窗口高度比例", "type": "number", "section": "ui.window"},
    {"key": "ui.window.min_width", "label": "最小宽度", "type": "number", "section": "ui.window"},
    {"key": "ui.window.min_height", "label": "最小高度", "type": "number", "section": "ui.window"},
    {"key": "dsh.host", "label": "dsh 绑定地址", "type": "string", "section": "dsh"},
    {"key": "dsh.port", "label": "dsh 端口", "type": "number", "section": "dsh"},
    {"key": "dsh.work_dir", "label": "dsh 工作目录", "type": "path", "section": "dsh"},
    {"key": "dsh.node", "label": "node 路径", "type": "path", "section": "dsh"},
    {"key": "dsh.dsh_bin", "label": "dsh bin.js 路径", "type": "path", "section": "dsh"},
    {"key": "dsh.profile_dir", "label": "dsh 浏览器 profile", "type": "path", "section": "dsh"},
    {"key": "dsh.start_timeout", "label": "dsh 启动超时", "type": "number", "section": "dsh"},
    {"key": "jupyter.host", "label": "Jupyter 绑定地址", "type": "string", "section": "jupyter"},
    {"key": "jupyter.port", "label": "Jupyter 端口", "type": "number", "section": "jupyter"},
    {"key": "jupyter.root_dir", "label": "Jupyter 工作目录", "type": "path", "section": "jupyter"},
    {"key": "jupyter.jupyter_bin", "label": "jupyter-lab 路径", "type": "path", "section": "jupyter"},
    {"key": "jupyter.profile_dir", "label": "Jupyter 浏览器 profile", "type": "path", "section": "jupyter"},
    {"key": "jupyter.start_timeout", "label": "Jupyter 启动超时", "type": "number", "section": "jupyter"},
    {"key": "jupyter.base_url", "label": "Jupyter base_url", "type": "string", "section": "jupyter"},
    {"key": "jupyter.kernel", "label": "默认内核", "type": "string", "section": "jupyter"},
    {
        "key": "jupyter.remember_per_workdir",
        "label": "按目录记忆内核",
        "type": "boolean",
        "section": "jupyter",
    },
)


@dataclass(frozen=True)
class _CachedReport:
    at: float
    profile: str
    timeout: float
    report: dsh_updates.UpdateReport


class ControlBackend:
    """控制台和 CLI 共用的服务动作集合。

    服务动作仍然走 ``TrayController`` / ``Supervisor``；这个类只负责把
    结果转成 JSON 友好的结构，并保护配置/内存的读取与重载。
    """

    def __init__(
        self,
        runtime: Runtime,
        controllers: dict[str, TrayController],
        *,
        request_quit: Any = None,
    ) -> None:
        self.runtime = runtime
        self.controllers = controllers
        self._request_quit = request_quit
        self._batch_lock = threading.Lock()
        self._config_lock = threading.Lock()
        self._update_lock = threading.Lock()
        self._cached_report: _CachedReport | None = None
        self._upgrade: UpgradeManager | None = None

    # ── 服务快照 ──────────────────────────────────────────────────────
    def _controller(self, service_id: str) -> TrayController:
        controller = self.controllers.get(service_id)
        if controller is None:
            raise ControlError(f"未知服务：{service_id}", status=404)
        return controller

    def _busy(self, controller: TrayController) -> bool:
        return controller.busy

    def _snapshot(
        self,
        controller: TrayController,
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
                "running": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        data = status.as_dict()
        data["id"] = context.service_id
        data["description"] = context.spec.description
        data["auto_start"] = context.definition.auto_start
        data["open_on_start"] = context.definition.open_on_start
        data["supports_updates"] = context.spec.supports_updates
        data["busy"] = self._busy(controller)
        data["status"] = "running" if status.running else "stopped"
        data["url"] = logs.redact(status.url or "") or None
        data["log"] = str(status.log_path)
        data["data_dir"] = str(status.data_dir)
        data["work_dir"] = str(status.work_dir)
        return data

    def services(self, *, detail: bool = False) -> list[dict[str, Any]]:
        rows = []
        for service_id in self.controllers:
            controller = self.controllers[service_id]
            rows.append(
                self._snapshot(
                    controller,
                    check_ports=True,
                    check_owner=detail,
                )
            )
        return rows

    def service(self, service_id: str) -> dict[str, Any]:
        controller = self._controller(service_id)
        data = self._snapshot(controller, check_ports=True, check_owner=True)
        context = controller.context
        data["doctor"] = [
            {"name": label, "value": value} for label, value in _service_doctor_rows(self.runtime, context)
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
            if action == "open-log":
                return controller.open_log()
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
                except Exception as exc:  # noqa: BLE001 - 批量操作逐个汇报
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
        path = self.runtime.paths.config
        try:
            raw = path.read_text("utf-8")
        except OSError:
            raw = ""
        data = config_mod.read_raw(path)
        values: dict[str, Any] = {}
        for field in CONFIG_FIELDS:
            key = str(field["key"])
            try:
                value = config_mod.get_value(path, key)
            except KeyError:
                value = _effective_config_value(self.runtime, key)
            values[key] = _jsonable(value)
        return {
            "path": str(path),
            "raw": raw,
            "parsed": _jsonable(data),
            "fields": [dict(field) for field in CONFIG_FIELDS],
            "values": values,
        }

    def _reload(self) -> None:
        """配置/记忆变更后重建上下文；运行中的服务不受影响。"""
        with self._config_lock:
            self.runtime.config = config_mod.load(self.runtime.paths.config)
            self.runtime.memory = memory.load(self.runtime.paths.memory)
            self._upgrade = None
            self._cached_report = None
            new_controllers: dict[str, TrayController] = {}
            for service_id in registry.ids():
                try:
                    context = self.runtime.context(service_id)
                except Exception:  # noqa: BLE001 - 配置错误留到操作时再报
                    continue
                new_controllers[service_id] = TrayController(context)
            self.controllers.clear()
            self.controllers.update(new_controllers)

    def set_config_value(self, key: str, value: Any) -> dict[str, Any]:
        path = self.runtime.paths.config
        config_mod.set_value(path, key, value)
        self._reload()
        return {"key": key, "value": value, "restart_required": True}

    def unset_config_value(self, key: str) -> dict[str, Any]:
        removed = config_mod.unset_value(self.runtime.paths.config, key)
        self._reload()
        return {"key": key, "removed": removed, "restart_required": True}

    def save_config_raw(self, raw: str) -> dict[str, Any]:
        try:
            tomllib.loads(raw)
        except tomllib.TOMLDecodeError as exc:
            raise ControlError(f"TOML 校验失败：{exc}") from exc
        paths_mod.write_atomic(self.runtime.paths.config, raw.rstrip() + "\n")
        self._reload()
        return {"saved": True, "restart_required": True}

    # ── 诊断 / 安装 / 目录 ────────────────────────────────────────────
    def doctor(self, service_ids: list[str] | None = None) -> list[dict[str, str]]:
        wanted = registry.split(",".join(service_ids)) if service_ids else None
        return [{"name": name, "value": value} for name, value in doctor.report(self.runtime, wanted)]

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
        if not value:
            if os.name == "nt":
                entries = []
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    drive = Path(f"{letter}:\\")
                    if drive.exists():
                        entries.append({"name": f"{letter}:\\", "path": str(drive), "dir": True})
                return {"path": "", "parent": None, "entries": entries}
            value = str(Path.home())
        path = Path(value).expanduser()
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise ControlError(f"无法解析目录：{exc}") from exc
        if resolved.is_file():
            resolved = resolved.parent
        if not resolved.is_dir():
            raise ControlError(f"目录不存在：{resolved}", status=404)
        entries: list[dict[str, Any]] = []
        try:
            for child in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
                try:
                    if child.is_dir():
                        entries.append({"name": child.name, "path": str(child), "dir": True})
                    elif include_files:
                        entries.append({"name": child.name, "path": str(child), "dir": False})
                except OSError:
                    continue
        except OSError as exc:
            raise ControlError(f"无法读取目录：{exc}") from exc
        parent = str(resolved.parent) if resolved.parent != resolved else None
        return {"path": str(resolved), "parent": parent, "entries": entries}

    # ── Jupyter ───────────────────────────────────────────────────────
    def _jupyter(self) -> ServiceContext:
        try:
            return self.runtime.context("jupyter")
        except Exception as exc:  # noqa: BLE001 - 缺少 jupyter 时返回可读错误
            raise ControlError(f"Jupyter 不可用：{type(exc).__name__}: {exc}") from exc

    def kernels(self) -> list[dict[str, Any]]:
        context = self._jupyter()
        install_info = context.adapter.install
        specs = jupyter_kernels.list_kernels(install_info, self.runtime.memory)
        default = getattr(context.settings, "kernel", None)
        rows = []
        for spec in specs:
            data = spec.as_dict()
            data["default"] = spec.name == default
            rows.append(data)
        return rows

    def add_kernel(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._jupyter()
        python_value = payload.get("python")
        directory = payload.get("dir")
        if directory:
            python = _python_from_dir(Path(str(directory)).expanduser())
        elif python_value:
            python = Path(str(python_value)).expanduser()
        else:
            raise ControlError("必须给出解释器路径，或包含 .venv 的项目目录")
        spec = jupyter_kernels.add_kernel(
            context.adapter.install,
            self.runtime.memory,
            python,
            name=str(payload.get("name") or "") or None,
            display_name=str(payload.get("display_name") or "") or None,
            replace=bool(payload.get("replace")),
            install_dependency=bool(payload.get("install_ipykernel")),
        )
        jupyter_workdirs.set_managed(self.runtime.memory, spec.name, spec.python)
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return spec.as_dict()

    def use_kernel(self, name: str) -> dict[str, Any]:
        context = self._jupyter()
        spec = jupyter_kernels.require_found(context.adapter.install, self.runtime.memory, name)
        if spec.broken:
            raise ControlError(f"内核 {spec.name} 的解释器不存在：{spec.python}")
        jupyter_workdirs.remember(self.runtime.memory, Path(context.settings.root_dir), spec.name)
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return {"kernel": spec.name, "restart_required": True}

    def rename_kernel(self, name: str, display_name: str) -> dict[str, Any]:
        context = self._jupyter()
        spec = jupyter_kernels.require_found(context.adapter.install, self.runtime.memory, name)
        renamed = jupyter_kernels.rename_kernel(spec, display_name)
        return renamed.as_dict()

    def remove_kernel(self, name: str, *, force: bool = False) -> dict[str, Any]:
        context = self._jupyter()
        spec = jupyter_kernels.require_found(context.adapter.install, self.runtime.memory, name)
        if not spec.managed and not force:
            raise ControlError("不是启动器注册的内核；确认删除请勾选强制删除")
        jupyter_kernels.remove_kernel(spec)
        table = memory.section(self.runtime.memory, "jupyter")
        if table.get("kernel") == spec.name:
            memory.set_value(self.runtime.memory, "jupyter", "kernel", None)
        mapping = table.get("workdir_kernels")
        if isinstance(mapping, dict):
            for key, value in list(mapping.items()):
                if value == spec.name:
                    mapping.pop(key, None)
        jupyter_workdirs.set_managed(self.runtime.memory, spec.name, None)
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return {"removed": spec.name}

    def workdirs(self) -> dict[str, Any]:
        context = self._jupyter()
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
        context = self._jupyter()
        workdir = jupyter_workdirs.normalize(value)
        if kernel:
            spec = jupyter_kernels.require_found(context.adapter.install, self.runtime.memory, kernel)
            if spec.broken:
                raise ControlError(f"内核 {spec.name} 的解释器不存在：{spec.python}")
        jupyter_workdirs.remember(self.runtime.memory, workdir, kernel)
        memory.save(self.runtime.memory, self.runtime.paths.memory)
        self._reload()
        return {"path": str(workdir), "restart_required": True}

    # ── 更新 ──────────────────────────────────────────────────────────
    def updates(
        self,
        *,
        refresh: bool = False,
        profile: str = "web",
        timeout: float = dsh_updates.DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        context = self.runtime.context("dsh")
        with self._update_lock:
            cached = self._cached_report
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
                self._cached_report = _CachedReport(time.monotonic(), profile, timeout, report)
            return report.as_dict()

    def _upgrade_manager(self) -> UpgradeManager:
        if self._upgrade is None:
            context = self.runtime.context("dsh")
            self._upgrade = UpgradeManager(context, exclusive=self._exclusive_dsh)
        return self._upgrade

    def _exclusive_dsh(self, work: Any) -> None:
        controller = self._controller("dsh")
        if not controller.try_begin():
            raise BusyError("dsh 有操作正在进行")
        try:
            work()
        finally:
            controller.end()

    def upgrade(
        self, targets: list[str], *, profile: str = "web", timeout: float = dsh_updates.DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        if not isinstance(targets, list) or not targets or not all(isinstance(item, str) for item in targets):
            raise ControlError("targets 必须是字符串数组")
        report = dsh_updates.check(
            self.runtime.context("dsh").settings,
            profile=profile,
            timeout=timeout,
        )
        with self._update_lock:
            self._cached_report = _CachedReport(time.monotonic(), profile, timeout, report)
        try:
            return self._upgrade_manager().start(targets, report)
        except BusyError as exc:
            raise ControlError(str(exc), status=409) from exc
        except UpgradeError as exc:
            raise ControlError(str(exc), status=400) from exc

    def upgrade_job(self) -> dict[str, Any]:
        manager = self._upgrade_manager()
        job = manager.job
        return job.as_dict() if job is not None else {"status": "idle"}

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


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


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
        "remember_per_workdir",
    )
    result: dict[str, Any] = {}
    for key in keys:
        if hasattr(settings, key):
            value = getattr(settings, key)
            result[key] = str(value) if isinstance(value, Path) else value
    return result


def _service_doctor_rows(runtime: Runtime, context: ServiceContext) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    try:
        rows.extend(context.adapter.doctor_rows())
    except Exception as exc:  # noqa: BLE001
        rows.append(("依赖", f"不可用: {type(exc).__name__}: {exc}"))
    status = context.service().status(check_owner=True)
    rows.append(("服务", "运行中" if status.running else "未运行"))
    rows.append(("监听", "LISTENING" if status.listening else "closed"))
    if status.owner:
        rows.append(("占用者", status.owner))
    return rows


def _effective_config_value(runtime: Runtime, key: str) -> Any:
    """没有显式配置项时给 UI 一个有效默认值。"""
    parts = key.split(".")
    if parts[0] == "launcher":
        return getattr(runtime.config.launcher, ".".join(parts[1:]), None)
    if parts[0] == "ui":
        if parts[1:2] == ["window"]:
            return getattr(runtime.config.ui.window, ".".join(parts[2:]), None)
        return getattr(runtime.config.ui, parts[1], None)
    try:
        context = runtime.context(parts[0])
    except Exception:
        return None
    return getattr(context.settings, ".".join(parts[1:]), None)


def _python_from_dir(directory: Path) -> Path:
    if directory.is_file():
        return directory
    if not directory.is_dir():
        raise ControlError(f"目录不存在：{directory}")
    candidates = (
        directory / ".venv" / "Scripts" / "python.exe",
        directory / ".venv" / "bin" / "python",
        directory / "venv" / "Scripts" / "python.exe",
        directory / "venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ControlError(f"{directory} 下没有找到 .venv/Scripts/python.exe 或 .venv/bin/python")


__all__ = ["CONFIG_FIELDS", "ControlBackend", "ControlError"]
