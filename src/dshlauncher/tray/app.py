"""pystray 适配层：图标、菜单、线程调度与托盘入口。"""

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

from .. import actions, paths, updates_panel
from ..context import Context
from ..settings import Settings
from ..upgrade import BusyError
from .controller import TrayController
from .ipc import START_WAIT, IpcServer, TrayUnavailable, _clear_info, _write_info, send_open
from .single import acquire_lock, release_lock

TITLE = "DeepSeek Harness"
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
    def __init__(self, settings: Settings, *, context: Context | None = None) -> None:
        self.context = context or Context.create(settings)
        self.settings = self.context.settings
        self.paths = self.context.paths
        self.controller = TrayController(self.context)
        self.icon: Any = None
        self.server: IpcServer | None = None
        self.panel: updates_panel.PanelServer | None = None
        self._details_lock = threading.Lock()
        self._panel_lock = threading.Lock()
        self._title_stop = threading.Event()
        self._refresh_lock = threading.Lock()
        self._refresh_timer: threading.Timer | None = None

    def run(self) -> int:
        import pystray

        self.icon = pystray.Icon("dshlauncher", icon_image(), TITLE, menu=self._menu(pystray))
        token = secrets.token_hex(16)
        self.server = IpcServer(self._ipc, token)
        self.server.start()
        _write_info(
            self.paths,
            {
                "pid": os.getpid(),
                "create_time": psutil.Process().create_time(),
                "port": self.server.port,
                "token": token,
            },
        )
        _print("托盘已启动：左键打开窗口，右键打开菜单。")
        try:
            self.icon.run(setup=self._setup)
        except KeyboardInterrupt:
            self.paths.audit("tray: Ctrl+C，停止服务后退出")
            with contextlib.suppress(Exception):
                self.controller.run_exclusive(self.controller.stop)
        finally:
            self._shutdown()
        return 0

    # ── 菜单 ──────────────────────────────────────────────────────────
    def _menu(self, pystray: Any) -> Any:
        menu_item = pystray.MenuItem
        return pystray.Menu(
            menu_item(
                "打开窗口",
                self._action("打开窗口", self.controller.open_window, quiet=True),
                default=True,
            ),
            menu_item(
                lambda item: f"服务状态：{self.controller.status_short()}…",
                self._details,
            ),
            menu_item("检查更新…", self._open_panel),
            pystray.Menu.SEPARATOR,
            menu_item("停止服务", self._action("停止服务", self._stop_service)),
            menu_item("重启服务", self._action("重启服务", self.controller.restart)),
            menu_item("刷新状态", lambda icon, item: self._refresh()),
            pystray.Menu.SEPARATOR,
            menu_item("查看日志", self._action("查看日志", self.controller.open_log)),
            menu_item("打开数据目录", self._action("打开数据目录", self.controller.open_data_dir)),
            pystray.Menu.SEPARATOR,
            menu_item("退出并停止服务", self._quit),
        )

    def _action(
        self, label: str, work: Callable[[], Any], *, quiet: bool = False
    ) -> Callable[[Any, Any], None]:
        """菜单回调必须立即返回：重活在后台线程里跑，避免卡住托盘消息循环。"""

        def handler(icon: Any, item: Any) -> None:
            if self.controller.stopping:
                if not quiet:
                    self._notify("托盘正在退出")
                return
            if not self.controller.try_begin():
                if not quiet:
                    self._notify(BUSY_TEXT)
                return
            threading.Thread(
                target=self._work, args=(label, work), name=f"dsh-tray-{label}", daemon=True
            ).start()

        return handler

    def _work(self, label: str, work: Callable[[], Any]) -> None:
        try:
            result = work()
            self.paths.audit(f"tray {label}: {result or 'ok'}")
        except Exception as exc:  # noqa: BLE001 - 托盘统一转成气泡 + 审计
            text = f"{label}失败：{type(exc).__name__}: {exc}"
            self.paths.audit(text, detail=traceback.format_exc())
            self._notify(text)
        finally:
            self.controller.end()
            self._schedule_refresh()

    # ── 动作 ──────────────────────────────────────────────────────────
    def _setup(self, icon: Any) -> None:
        icon.visible = True
        threading.Thread(target=self._title_loop, daemon=True).start()
        try:
            result = self.controller.run_exclusive(self.controller.open_window)
            self.paths.audit("tray open: " + result)
        except Exception as exc:  # noqa: BLE001 - 托盘启动失败也要留在任务栏
            text = f"打开窗口失败：{type(exc).__name__}: {exc}"
            self.paths.audit(text, detail=traceback.format_exc())
            self._notify(text)
        self._schedule_refresh()

    def _stop_service(self) -> str:
        return "已停止服务" if self.controller.stop() else "服务未在运行"

    def _exclusive(self, work: Callable[[], None]) -> None:
        """升级期间占住托盘的服务动作锁，避免与停止/重启交叉。"""
        if not self.controller.try_begin():
            raise BusyError(BUSY_TEXT)
        try:
            work()
        finally:
            self.controller.end()

    def _open_panel(self, icon: Any = None, item: Any = None) -> None:
        if self.controller.stopping:
            return
        if not self._panel_lock.acquire(blocking=False):
            self._notify("更新面板正在打开")
            return
        threading.Thread(target=self._show_panel, name="dsh-tray-panel", daemon=True).start()

    def _show_panel(self) -> None:
        try:
            if self.panel is None:
                self.panel = updates_panel.PanelServer(self.context, exclusive=self._exclusive)
                self.panel.start()
            result = self.panel.open_window()
            self.paths.audit(f"tray 更新面板: {result} {self.panel.url}")
        except Exception as exc:  # noqa: BLE001 - 托盘动作统一转成气泡 + 审计
            text = f"打开更新面板失败：{type(exc).__name__}: {exc}"
            self.paths.audit(text, detail=traceback.format_exc())
            self._notify(text)
        finally:
            self._panel_lock.release()

    def _details(self, icon: Any = None, item: Any = None) -> None:
        """菜单只显示短状态；详情放进原生弹窗，避免菜单过宽。"""
        if self.controller.stopping or not self._details_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._show_details, name="dsh-tray-details", daemon=True).start()

    def _show_details(self) -> None:
        try:
            text = self.controller.describe()
        except Exception as exc:  # noqa: BLE001 - 弹窗仍然要显示失败原因
            text = f"读取状态失败：{type(exc).__name__}: {exc}"
            self.paths.audit(text, detail=traceback.format_exc())
        try:
            self.paths.audit("tray 服务状态: " + (text.splitlines() or [""])[0])
            self.context.backend.message(f"{TITLE} 服务状态", text)
        except Exception as exc:  # noqa: BLE001 - 弹窗失败也要留痕
            self.paths.audit(
                f"tray 服务状态失败: {type(exc).__name__}: {exc}",
                detail=traceback.format_exc(),
            )
            self._notify(f"打开状态窗口失败：{exc}")
        finally:
            self._details_lock.release()

    def _ipc(self, command: str) -> str:
        if command != "open":
            raise ValueError(f"未知命令：{command}")
        if self.controller.stopping:
            raise RuntimeError("托盘正在退出")
        result = self.controller.run_exclusive(self.controller.open_window)
        self.paths.audit("tray ipc open: " + result)
        self._schedule_refresh()
        return result

    def _quit(self, icon: Any = None, item: Any = None) -> None:
        if self.controller.stopping:
            return
        self.controller.mark_stopping()
        threading.Thread(target=self._stop_and_quit, name="dsh-tray-quit", daemon=True).start()

    def _stop_and_quit(self) -> None:
        try:
            stopped = self.controller.run_exclusive(self.controller.stop)
            self.paths.audit("tray quit: " + ("服务已停止" if stopped else "服务未在运行"))
        except Exception as exc:  # noqa: BLE001 - 停服务失败也要退出托盘
            self.paths.audit(
                f"tray quit: 停止服务失败 {type(exc).__name__}: {exc}",
                detail=traceback.format_exc(),
            )
            self._notify(f"停止服务失败：{exc}")
        with contextlib.suppress(Exception):
            self.icon.stop()

    # ── 刷新 / 通知 / 收尾 ───────────────────────────────────────────
    def _title_loop(self) -> None:
        while not self._title_stop.wait(TITLE_INTERVAL):
            self._refresh_title()

    def _refresh_title(self) -> None:
        with contextlib.suppress(Exception):
            self.icon.title = f"{TITLE} — {self.controller.status_tooltip()}"

    def _refresh(self) -> None:
        self._refresh_title()
        with contextlib.suppress(Exception):
            self.icon.update_menu()

    def _schedule_refresh(self) -> None:
        """合并连续动作的菜单重建，避免频繁销毁/创建菜单句柄。"""
        with self._refresh_lock:
            if self._refresh_timer is not None and self._refresh_timer.is_alive():
                return
            self._refresh_timer = threading.Timer(REFRESH_DELAY, self._refresh)
            self._refresh_timer.daemon = True
            self._refresh_timer.start()

    def _notify(self, text: str) -> None:
        rows = [row for row in str(text).splitlines() if row.strip()]
        message = "\n".join(rows[:4])
        if len(message) > 250:
            message = message[:247] + "…"
        with contextlib.suppress(Exception):
            self.icon.notify(message, TITLE)

    def _shutdown(self) -> None:
        self.controller.mark_stopping()
        self._title_stop.set()
        with self._refresh_lock:
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
        if self.server is not None:
            self.server.close()
        if self.panel is not None:
            self.panel.close()
        _clear_info(self.paths)


# ── 入口 ──────────────────────────────────────────────────────────────
def _print(text: str) -> None:
    if sys.stdout is None:
        return
    with contextlib.suppress(OSError):
        print(text)


def _open_directly(context: Context) -> int:
    result = actions.open_dsh(context)
    context.paths.audit("open: " + result)
    _print(result)
    return 0


def _report_request_error(exc: BaseException, paths_: paths.Paths) -> int:
    # 托盘已经在气泡里报过错了，这里只落日志（有控制台时顺带打印），不再弹窗。
    text = f"托盘请求失败：{type(exc).__name__}: {exc}"
    paths_.audit(text)
    _print(text)
    return 1


def run(settings: Settings, *, context: Context | None = None) -> int:
    """双击 / ``tray`` 的入口：有托盘就投递，没有就自己成为托盘。"""
    context = context or Context.create(settings)
    paths_ = context.paths
    timeout = context.settings.start_timeout + 30
    try:
        result = send_open(paths_, timeout, wait=0.0)
    except TrayUnavailable:
        pass
    except RuntimeError as exc:
        return _report_request_error(exc, paths_)
    else:
        _print(result)
        return 0

    lock = acquire_lock(paths_)
    if lock is None:
        # 另一个实例正在启动托盘：等它就绪后把 open 投递过去。
        try:
            result = send_open(paths_, timeout, wait=START_WAIT)
        except TrayUnavailable:
            return _open_directly(context)
        except RuntimeError as exc:
            return _report_request_error(exc, paths_)
        _print(result)
        return 0

    try:
        return TrayApp(context.settings, context=context).run()
    finally:
        release_lock(lock)
