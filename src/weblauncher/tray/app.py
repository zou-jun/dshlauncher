"""pystray 适配层：多服务菜单、线程调度与托盘入口。"""

from __future__ import annotations

import contextlib
import os
import secrets
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from .. import logs, paths
from ..context import Runtime, ServiceContext
from ..services.dsh import panel as dsh_panel
from ..services.dsh.upgrade import BusyError
from .controller import TrayController
from .ipc import START_WAIT, IpcServer, TrayUnavailable, _clear_info, _write_info, send_open
from .single import acquire_lock, release_lock

TITLE = "Web 服务启动器"
ICON_SIZE = 64
TITLE_INTERVAL = 2.0
REFRESH_DELAY = 0.15
BUSY_TEXT = "有操作正在进行，请稍后再试"


def _icon_candidates() -> list[Path]:
    candidates: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "assets" / "app.png")
    root = paths.executable_dir()
    candidates.append(root / "assets" / "app.png")
    candidates.append(root / "packaging" / "assets" / "app.png")
    return candidates


def icon_image() -> Any:
    """托盘图标（PIL Image）；找不到图片时抛错，由调用方提示。"""
    from PIL import Image

    for candidate in _icon_candidates():
        try:
            with Image.open(candidate) as image:
                return image.convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
        except OSError:
            continue
    raise RuntimeError("找不到托盘图标：assets/app.png")


class TrayApp:
    def __init__(self, runtime: Runtime, *, contexts: list[ServiceContext] | None = None) -> None:
        self.runtime = runtime
        self.contexts = contexts if contexts is not None else runtime.contexts()
        self.controllers: dict[str, TrayController] = {
            context.service_id: TrayController(context) for context in self.contexts
        }
        self.icon: Any = None
        self.server: IpcServer | None = None
        self.panel: dsh_panel.PanelServer | None = None
        self._details_lock = threading.Lock()
        self._panel_lock = threading.Lock()
        self._batch_lock = threading.Lock()
        self._title_stop = threading.Event()
        self._refresh_lock = threading.Lock()
        self._refresh_timer: threading.Timer | None = None
        self._stopping = threading.Event()
        self._lock: Any = None

    # ── 入口 ──────────────────────────────────────────────────────────
    def run(self) -> int:
        import pystray

        self.icon = pystray.Icon("weblauncher", icon_image(), TITLE, menu=self._menu(pystray))
        token = secrets.token_hex(16)
        self.server = IpcServer(self._ipc, token)
        self.server.start()
        _write_info(
            self.runtime.paths,
            {
                "pid": os.getpid(),
                "create_time": psutil.Process().create_time(),
                "port": self.server.port,
                "token": token,
            },
        )
        _print("托盘已启动：左键打开服务，右键打开菜单。")
        try:
            self.icon.run(setup=self._setup)
        except KeyboardInterrupt:
            if self.runtime.config.launcher.tray_exit_stops_services:
                self.runtime.paths.audit("tray: Ctrl+C，停止全部服务后退出")
                with contextlib.suppress(Exception):
                    self._batch("stop", wait=True)
            else:
                self.runtime.paths.audit("tray: Ctrl+C，服务继续运行")
        finally:
            self._shutdown()
        return 0

    # ── 菜单 ──────────────────────────────────────────────────────────
    def _menu(self, pystray: Any) -> Any:
        menu_item = pystray.MenuItem
        menu = pystray.Menu
        entries: list[Any] = []
        for context in self.contexts:
            controller = self.controllers[context.service_id]
            entries.append(
                menu_item(
                    lambda item, c=controller: f"{c.context.spec.label} · {c.status_short()}",
                    menu(
                        menu_item(
                            "打开",
                            self._action(controller, "打开", controller.open_window),
                        ),
                        menu_item(
                            lambda item, c=controller: f"状态：{c.status_short()}…",
                            self._details(controller),
                        ),
                        menu.SEPARATOR,
                        menu_item("启动", self._action(controller, "启动", controller.start)),
                        menu_item("停止", self._action(controller, "停止", controller.stop)),
                        menu_item("重启", self._action(controller, "重启", controller.restart)),
                        menu.SEPARATOR,
                        menu_item("查看日志", self._action(controller, "日志", controller.open_log)),
                        menu_item(
                            "打开数据目录",
                            self._action(controller, "数据目录", controller.open_data_dir),
                        ),
                    ),
                )
            )
        entries.extend(
            [
                menu.SEPARATOR,
                menu_item("启动全部", self._action(None, "启动全部", lambda: self._batch("start"))),
                menu_item("停止全部", self._action(None, "停止全部", lambda: self._batch("stop"))),
                menu_item("刷新状态", lambda icon, item: self._refresh()),
            ]
        )
        if self._dsh_controller() is not None:
            entries.extend([menu.SEPARATOR, menu_item("检查更新…", self._open_panel)])
        entries.extend(
            [
                menu.SEPARATOR,
                menu_item("退出（服务继续）", self._quit),
                menu_item("退出并停止全部服务", self._stop_and_quit),
            ]
        )
        return menu(*entries)

    def _action(
        self,
        controller: TrayController | None,
        label: str,
        work: Callable[[], Any],
        *,
        quiet: bool = False,
    ) -> Callable[[Any, Any], None]:
        """菜单回调必须立即返回：重活在后台线程里跑，避免卡住托盘消息循环。"""

        def handler(icon: Any, item: Any) -> None:
            if self._stopping.is_set():
                if not quiet:
                    self._notify("托盘正在退出")
                return
            if controller is not None:
                if not controller.try_begin():
                    if not quiet:
                        self._notify(BUSY_TEXT)
                    return
            elif not self._batch_lock.acquire(blocking=False):
                if not quiet:
                    self._notify(BUSY_TEXT)
                return
            threading.Thread(
                target=self._work,
                args=(controller, label, work),
                name=f"tray-{label}",
                daemon=True,
            ).start()

        return handler

    def _work(self, controller: TrayController | None, label: str, work: Callable[[], Any]) -> None:
        try:
            result = work()
            self.runtime.paths.audit(f"tray {label}: {result or 'ok'}")
        except Exception as exc:  # noqa: BLE001 - 托盘统一转成气泡 + 审计
            text = f"{label}失败：{type(exc).__name__}: {exc}"
            self.runtime.paths.audit(text, detail=traceback.format_exc())
            self._notify(text)
        finally:
            if controller is not None:
                controller.end()
            else:
                self._batch_lock.release()
            self._schedule_refresh()

    # ── 动作 ──────────────────────────────────────────────────────────
    def _setup(self, icon: Any) -> None:
        icon.visible = True
        threading.Thread(target=self._title_loop, daemon=True).start()
        for context in self.contexts:
            if not context.definition.auto_start:
                continue
            controller = self.controllers[context.service_id]
            try:

                def bring_up(ctrl=controller, ctx=context) -> None:
                    ctrl.start()
                    state = ctrl.service.read_state()
                    self.runtime.paths.audit(f"tray 启动 {ctx.service_id}: pid={getattr(state, 'pid', '-')}")
                    if ctx.definition.open_on_start and not self._stopping.is_set():
                        ctrl.open_window()
                        self.runtime.paths.audit(f"tray 打开 {ctx.service_id}")

                controller.run_exclusive(bring_up)
            except Exception as exc:  # noqa: BLE001 - 托盘启动失败也要留在任务栏
                text = f"{context.spec.label} 启动失败：{type(exc).__name__}: {exc}"
                self.runtime.paths.audit(text, detail=traceback.format_exc())
                self._notify(text)
        self._schedule_refresh()

    def _batch(self, action: str, *, wait: bool = False) -> str:
        ordered = sorted(self.controllers.values(), key=lambda ctrl: ctrl.context.service_id)
        acquired = contextlib.ExitStack()
        try:
            for controller in ordered:
                if wait:
                    acquired.enter_context(controller.held())
                elif controller.try_begin():
                    acquired.callback(controller.end)
                else:
                    raise BusyError(BUSY_TEXT)
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
                except Exception as exc:  # noqa: BLE001 - 一个服务失败不能阻断其余服务
                    errors.append(f"{label}: {type(exc).__name__}: {exc}")
            if errors:
                raise RuntimeError("；".join(errors))
            return "；".join(results)
        finally:
            acquired.close()

    def _default_contexts(self) -> list[ServiceContext]:
        return [context for context in self.contexts if context.definition.open_on_start]

    def _open_defaults(self) -> str:
        results = []
        for context in self._default_contexts():
            controller = self.controllers[context.service_id]
            results.append(f"{context.spec.label}: {controller.run_exclusive(controller.open_window)}")
        return "；".join(results)

    def _dsh_controller(self) -> TrayController | None:
        for context in self.contexts:
            if context.service_id == "dsh":
                return self.controllers["dsh"]
        return None

    # ── 详情 / 更新面板 ───────────────────────────────────────────────
    def _details(self, controller: TrayController) -> Callable[[Any, Any], None]:
        def handler(icon: Any, item: Any) -> None:
            if not self._details_lock.acquire(blocking=False):
                self._notify("状态窗口正在打开")
                return
            try:
                self._show_details(controller)
            finally:
                self._details_lock.release()

        return handler

    def _show_details(self, controller: TrayController) -> None:
        try:
            text = controller.describe()
        except Exception as exc:  # noqa: BLE001 - 读状态失败也要给出原因
            text = f"读取状态失败：{type(exc).__name__}: {exc}"
            self.runtime.paths.audit(text, detail=traceback.format_exc())
        try:
            self.runtime.backend.message(
                f"{TITLE} · {controller.context.spec.label}",
                logs.redact(text),
            )
        except Exception as exc:  # noqa: BLE001 - 没有原生对话框时退回气泡
            self._notify(f"打开状态窗口失败：{type(exc).__name__}: {exc}")

    def _open_panel(self, icon: Any = None, item: Any = None) -> None:
        if self._stopping.is_set():
            return
        if not self._panel_lock.acquire(blocking=False):
            self._notify("更新面板正在打开")
            return
        threading.Thread(target=self._show_panel, name="tray-panel", daemon=True).start()

    def _show_panel(self) -> None:
        try:
            controller = self._dsh_controller()
            if controller is None:
                raise RuntimeError("没有可更新的服务")
            if self.panel is None:
                self.panel = dsh_panel.PanelServer(controller.context, exclusive=self._exclusive)
                self.panel.start()
            result = self.panel.open_window()
            self.runtime.paths.audit(f"tray 更新面板: {result} port={getattr(self.panel, 'port', '?')}")
        except Exception as exc:  # noqa: BLE001 - 托盘动作统一转成气泡 + 审计
            text = f"打开更新面板失败：{type(exc).__name__}: {exc}"
            self.runtime.paths.audit(text, detail=traceback.format_exc())
            self._notify(text)
        finally:
            self._panel_lock.release()

    def _exclusive(self, work: Callable[[], None]) -> None:
        """升级期间占住 dsh 的服务动作锁，避免与停止/重启交叉。"""
        controller = self._dsh_controller()
        if controller is None or not controller.try_begin():
            raise BusyError(BUSY_TEXT)
        try:
            work()
        finally:
            controller.end()

    # ── 退出 ──────────────────────────────────────────────────────────
    def _quit(self, icon: Any = None, item: Any = None) -> None:
        self._stopping.set()
        self.runtime.paths.audit("tray: 退出（服务继续运行）")
        if self.icon is not None:
            self.icon.stop()

    def _stop_and_quit(self, icon: Any = None, item: Any = None) -> None:
        self._stopping.set()
        try:
            self._batch("stop", wait=True)
        except Exception as exc:  # noqa: BLE001 - 停不下来也要移除图标
            self.runtime.paths.audit(f"tray 退出停止服务失败: {exc}", detail=traceback.format_exc())
            self._notify(f"停止服务失败：{type(exc).__name__}: {exc}")
        if self.icon is not None:
            self.icon.stop()

    def _shutdown(self) -> None:
        self._title_stop.set()
        if self.server is not None:
            self.server.close()
        _clear_info(self.runtime.paths)
        if self.panel is not None:
            with contextlib.suppress(Exception):
                self.panel.close()
        with contextlib.suppress(Exception):
            from .single import release_lock as _release

            if self._lock is not None:
                _release(self._lock)
        self._lock = None

    # ── 刷新 / IPC ────────────────────────────────────────────────────
    def _ipc(self, command: str) -> str:
        if self._stopping.is_set():
            raise RuntimeError("托盘正在退出")
        parts = command.split(maxsplit=1)
        action = parts[0] if parts else ""
        target = parts[1].strip() if len(parts) > 1 else ""
        if action == "open":
            if target:
                controller = self.controllers.get(target)
                if controller is None:
                    raise RuntimeError(f"未知服务：{target}")
                return controller.run_exclusive(controller.open_window)
            return self._open_defaults()
        if action == "refresh":
            self._schedule_refresh()
            return "refreshed"
        raise RuntimeError(f"未知命令：{command}")

    def _refresh(self) -> None:
        if self.icon is not None:
            with contextlib.suppress(Exception):
                self.icon.title = self._title()
                self.icon.update_menu()

    def _schedule_refresh(self) -> None:
        with self._refresh_lock:
            if self._refresh_timer is not None:
                return
            timer = threading.Timer(REFRESH_DELAY, self._run_refresh)
            timer.daemon = True
            self._refresh_timer = timer
            timer.start()

    def _run_refresh(self) -> None:
        with self._refresh_lock:
            self._refresh_timer = None
        self._refresh()

    def _title(self) -> str:
        parts = []
        for controller in self.controllers.values():
            try:
                running = controller.service.status(check_ports=False).running
            except Exception:
                running = False
            parts.append(f"{controller.context.spec.label} {'●' if running else '○'}")
        return f"{TITLE}  " + " · ".join(parts)

    def _title_loop(self) -> None:
        while not self._title_stop.is_set():
            self._refresh()
            self._title_stop.wait(TITLE_INTERVAL)

    def _notify(self, message: str) -> None:
        if self.icon is not None:
            with contextlib.suppress(Exception):
                self.icon.notify(message, TITLE)


def _print(text: str) -> None:
    if sys.stdout is not None:
        with contextlib.suppress(OSError):
            print(text)


def run(runtime: Runtime) -> int:
    """双击入口：有托盘就投递打开；没有就自己成为托盘。"""
    open_timeout = runtime.config.launcher.start_timeout + 30.0
    try:
        send_open(runtime.paths, timeout=open_timeout)
        return 0
    except TrayUnavailable:
        pass

    lock = acquire_lock(runtime.paths)
    if lock is None:
        # 另一个托盘正在启动：等它就绪后投递，失败则直接打开默认服务。
        try:
            send_open(runtime.paths, timeout=open_timeout, wait=START_WAIT)
            return 0
        except TrayUnavailable:
            app = TrayApp(runtime)
            with contextlib.suppress(Exception):
                app._open_defaults()
            return 0

    app = TrayApp(runtime)
    app._lock = lock
    try:
        return app.run()
    finally:
        release_lock(lock)
