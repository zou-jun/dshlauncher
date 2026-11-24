"""常驻 Agent：最小托盘入口、控制台 HTTP 服务与动作编排。"""

from __future__ import annotations

import contextlib
import os
import secrets
import sys
import threading
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil

from .. import browser, paths
from ..context import Runtime, ServiceContext
from ..control.backend import ControlBackend
from ..control.server import ControlServer
from ..controller import ServiceController, ServiceControllerRegistry
from ..services.dsh.upgrade import BusyError
from .ipc import START_WAIT, IpcServer, TrayUnavailable, _clear_info, _write_info, send_ui
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


def console_settings(runtime: Runtime) -> SimpleNamespace:
    """浏览器打开控制台时使用的 profile 与窗口参数。"""
    single = bool(runtime.config.ui.single_window)
    return SimpleNamespace(
        browser=runtime.config.ui.browser,
        ozone=runtime.config.ui.ozone,
        dedupe=True,
        single_window=single,
        profile_dir=runtime.paths.tabbed_profile if single else runtime.paths.control_profile,
        window_kwargs=runtime.config.ui.window.kwargs,
    )


def open_console_url(runtime: Runtime, url: str) -> str:
    """用独立 Chromium 配置打开控制台的一次性入口。"""
    return browser.launch(
        console_settings(runtime),
        url,
        backend=runtime.backend,
        dedupe=True,
    )


class TrayApp:
    def __init__(
        self,
        runtime: Runtime,
        *,
        contexts: list[ServiceContext] | None = None,
        target: str = "/#/",
        open_console: bool = True,
    ) -> None:
        self.runtime = runtime
        loaded = contexts if contexts is not None else runtime.contexts()
        self.controllers = ServiceControllerRegistry(
            {context.service_id: ServiceController(context) for context in loaded},
            errors=dict(runtime.errors),
        )
        self.target = target
        self.open_console = open_console
        self.icon: Any = None
        self.server: IpcServer | None = None
        self.control: ControlServer | None = None
        self.backend: ControlBackend | None = None
        self._control_lock = threading.Lock()
        self._title_stop = threading.Event()
        self._refresh_lock = threading.Lock()
        self._refresh_timer: threading.Timer | None = None
        self._stopping = threading.Event()
        self._last_console_open = 0.0
        self._lock: Any = None

    # ── 入口 ──────────────────────────────────────────────────────────
    def run(self) -> int:
        import pystray

        self.icon = pystray.Icon("weblauncher", icon_image(), TITLE, menu=self._menu(pystray))
        self.backend = ControlBackend(
            self.runtime,
            self.controllers,
            request_quit=self._request_quit,
        )
        self.control = ControlServer(self.backend)
        self.control.start()
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
                "control": self.control.port,
            },
        )
        _print(f"控制台已启动：{self.control.base_url}/")
        try:
            self.icon.run(setup=self._setup)
        except KeyboardInterrupt:
            if self.runtime.config.launcher.tray_exit_stops_services:
                self.runtime.paths.audit("agent: Ctrl+C，停止全部服务后退出")
                with contextlib.suppress(Exception):
                    self._batch("stop", wait=True)
            else:
                self.runtime.paths.audit("agent: Ctrl+C，服务继续运行")
        finally:
            self._shutdown()
        return 0

    # ── 托盘：只保留入口，业务全部在 Web 控制台 ─────────────────────
    def _menu(self, pystray: Any) -> Any:
        menu_item = pystray.MenuItem
        menu = pystray.Menu
        return menu(
            menu_item("打开控制台", self._console_action, default=True),
            menu.SEPARATOR,
            menu_item("退出（服务继续）", self._quit),
            menu_item("退出并停止全部服务", self._stop_and_quit),
        )

    def _console_action(self, icon: Any = None, item: Any = None) -> None:
        if self._stopping.is_set():
            return
        now = time.monotonic()
        # Windows 托盘的双击可能产生两次激活；一次窗口操作足够。
        if now - self._last_console_open < 0.6:
            return
        self._last_console_open = now
        threading.Thread(target=self._open_console_safe, name="console-open", daemon=True).start()

    def _open_console_safe(self) -> None:
        try:
            result = self._open_console()
            self.runtime.paths.audit(f"agent: 打开控制台 {result}")
        except Exception as exc:  # noqa: BLE001 - 失败也留在托盘
            text = f"打开控制台失败：{type(exc).__name__}: {exc}"
            self.runtime.paths.audit(text, detail=traceback.format_exc())
            self._notify(text)

    def _open_console(self) -> str:
        if self.control is None:
            raise RuntimeError("控制台服务尚未启动")
        with self._control_lock:
            return open_console_url(self.runtime, self.control.bootstrap_url(self.target))

    def _setup(self, icon: Any) -> None:
        icon.visible = True
        threading.Thread(target=self._title_loop, name="agent-title", daemon=True).start()
        threading.Thread(target=self._startup, name="agent-startup", daemon=True).start()

    def _startup(self) -> None:
        # 只打开控制台；服务由用户在控制台里显式启动，Agent 启动不拉起任何服务。
        if self.open_console:
            self._open_console_safe()
        self._schedule_refresh()

    # ── 批量 / IPC ────────────────────────────────────────────────────
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

    def _ipc(self, command: str) -> str:
        if self._stopping.is_set():
            raise RuntimeError("控制台正在退出")
        parts = command.split(maxsplit=1)
        action = parts[0] if parts else ""
        target = parts[1].strip() if len(parts) > 1 else ""
        if action == "ui":
            if self.control is None:
                raise RuntimeError("控制台服务尚未启动")
            return self.control.bootstrap_url(target or "/#/")
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

    def _open_defaults(self) -> str:
        results = []
        for controller in self.controllers.values():
            if not controller.context.spec.open_on_start:
                continue
            results.append(
                f"{controller.context.spec.label}: {controller.run_exclusive(controller.open_window)}"
            )
        return "；".join(results)

    # ── 退出 ──────────────────────────────────────────────────────────
    def _request_quit(self, *, stop_services: bool = False) -> None:
        if stop_services:
            self._stop_and_quit()
        else:
            self._quit()

    def _quit(self, icon: Any = None, item: Any = None) -> None:
        self._stopping.set()
        self.runtime.paths.audit("agent: 退出（服务继续运行）")
        if self.icon is not None:
            self.icon.stop()

    def _stop_and_quit(self, icon: Any = None, item: Any = None) -> None:
        self._stopping.set()
        try:
            self._batch("stop", wait=True)
        except Exception as exc:  # noqa: BLE001 - 停不下来也要移除图标
            self.runtime.paths.audit(f"agent 退出停止服务失败: {exc}", detail=traceback.format_exc())
            self._notify(f"停止服务失败：{type(exc).__name__}: {exc}")
        if self.icon is not None:
            self.icon.stop()

    def _shutdown(self) -> None:
        self._title_stop.set()
        if self.control is not None:
            with contextlib.suppress(Exception):
                self.control.close()
        if self.server is not None:
            self.server.close()
        _clear_info(self.runtime.paths)
        if self._lock is not None:
            with contextlib.suppress(Exception):
                release_lock(self._lock)
        self._lock = None

    # ── 状态 / 通知 ───────────────────────────────────────────────────
    def _refresh(self) -> None:
        if self.icon is not None:
            with contextlib.suppress(Exception):
                self.icon.title = self._title()

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


def run(runtime: Runtime, *, target: str = "/#/") -> int:
    """双击 / no-args：有控制台就投递入口，没有就成为常驻 Agent。"""
    open_timeout = runtime.config.launcher.start_timeout + 30.0
    try:
        url = send_ui(runtime.paths, timeout=open_timeout, target=target)
        open_console_url(runtime, url)
        return 0
    except TrayUnavailable:
        pass
    except Exception as exc:  # noqa: BLE001 - 打开浏览器失败不应启动第二实例
        runtime.paths.audit(f"打开控制台失败: {type(exc).__name__}: {exc}")

    lock = acquire_lock(runtime.paths)
    if lock is None:
        # 另一个 Agent 正在启动：等它写出 IPC 信息后投递入口。
        try:
            url = send_ui(runtime.paths, timeout=open_timeout, wait=START_WAIT, target=target)
            open_console_url(runtime, url)
            return 0
        except TrayUnavailable:
            return 0

    app = TrayApp(runtime, target=target)
    app._lock = lock
    try:
        return app.run()
    finally:
        release_lock(lock)
