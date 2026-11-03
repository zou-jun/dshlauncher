"""tkinter 控制面板（缺 tk 时降级为终端菜单）：状态 + 打开 / 停止 / 重启。

Linux 上 uv / PyInstaller 自带的 Tk 可能是 ``no-xft`` 构建，只能画核心 X
字体里的 ASCII：这种情况下面板自动切换到英文标签与英文状态，避免出现
"按钮没有文字"。
"""

from __future__ import annotations

import queue
import sys
import threading
from collections.abc import Callable
from typing import Any

from . import actions, paths, platform, service
from .settings import Settings

CJK_LABELS = {
    "title": "DeepSeek Harness 控制台",
    "initial": "读取状态…",
    "open": "打开窗口",
    "stop": "停止服务",
    "restart": "重启服务",
    "refresh": "刷新",
    "log": "查看日志",
    "close": "关闭",
    "opening": "启动并打开窗口…",
    "stopping": "停止服务…",
    "restarting": "重启服务…",
    "error": "操作失败",
}

ASCII_LABELS = {
    "title": "dshlauncher",
    "initial": "Loading…",
    "open": "Open",
    "stop": "Stop",
    "restart": "Restart",
    "refresh": "Refresh",
    "log": "Log",
    "close": "Close",
    "opening": "Starting and opening…",
    "stopping": "Stopping…",
    "restarting": "Restarting…",
    "error": "Error",
}


class Panel:
    def __init__(self, settings: Settings, *, ascii_only: bool = False) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.settings = settings
        self.ascii_only = ascii_only
        self.labels = ASCII_LABELS if ascii_only else CJK_LABELS
        self.controller = service.Service(settings)

        self.root = tk.Tk()
        self.root.title(self.labels["title"])
        self.root.geometry("680x340")
        self.root.minsize(560, 300)

        self._results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._busy = False

        self._status = tk.StringVar(value=self.labels["initial"])
        self._label = tk.Label(
            self.root,
            textvariable=self._status,
            justify="left",
            anchor="nw",
            font=("Consolas", 10),
        )
        self._label.pack(fill="both", expand=True, padx=14, pady=(14, 8))

        bar = tk.Frame(self.root)
        bar.pack(fill="x", padx=14, pady=(0, 14))

        self._buttons: list[ttk.Button] = []
        buttons = (
            (self.labels["open"], self._open),
            (self.labels["stop"], self._stop),
            (self.labels["restart"], self._restart),
            (self.labels["refresh"], self.refresh),
            (self.labels["log"], self._log),
            (self.labels["close"], self.root.destroy),
        )
        for text, handler in buttons:
            button = ttk.Button(bar, text=text, command=handler)
            button.pack(side="left", padx=(0, 8))
            self._buttons.append(button)

        self.refresh()
        self.root.bind("<Configure>", self._on_configure)
        self.root.after(120, self._drain)

    def run(self) -> None:
        self.root.mainloop()

    def refresh(self) -> None:
        self._status.set(self.controller.describe(english=self.ascii_only))

    def _on_configure(self, event) -> None:  # noqa: ANN001 - tkinter 事件
        if event.widget is self.root:
            self._label.configure(wraplength=max(240, int(event.width) - 40))

    def _open(self) -> None:
        self._submit(self.labels["opening"], lambda: actions.open_dsh(self.settings))

    def _stop(self) -> None:
        def work() -> str:
            stopped = self.controller.stop()
            if self.ascii_only:
                return "stopped" if stopped else "not running"
            return "已停止" if stopped else "服务未在运行"

        self._submit(self.labels["stopping"], work)

    def _restart(self) -> None:
        self._submit(self.labels["restarting"], lambda: actions.restart(self.settings))

    def _log(self) -> None:
        paths.ensure_data_dir()
        paths.log_path().touch(exist_ok=True)
        platform.load().open_path(paths.log_path())

    def _submit(self, label: str, work: Callable[[], Any]) -> None:
        if self._busy:
            return
        self._busy = True
        for button in self._buttons:
            button.state(["disabled"])
        self._status.set(label)
        threading.Thread(target=self._run_work, args=(work,), daemon=True).start()

    def _run_work(self, work: Callable[[], Any]) -> None:
        try:
            self._results.put(("ok", work()))
        except Exception as exc:  # noqa: BLE001 - 面板统一展示失败原因
            paths.audit(f"ui error: {type(exc).__name__}: {exc}")
            self._results.put(("err", exc))

    def _drain(self) -> None:
        from tkinter import messagebox

        try:
            while True:
                kind, payload = self._results.get_nowait()
                self._busy = False
                for button in self._buttons:
                    button.state(["!disabled"])
                if kind == "err":
                    text = str(payload)
                    if self.ascii_only:
                        # 当前 Tk 画不出中文，异常文本多半是中文；详情看审计日志。
                        text = f"{type(payload).__name__}\n\nSee: {paths.launcher_log_path()}"
                    messagebox.showerror(self.labels["error"], text, parent=self.root)
                self.refresh()
        except queue.Empty:
            pass
        self.root.after(150, self._drain)


def _console_menu(settings: Settings) -> None:
    controller = service.Service(settings)
    choices = {
        "1": ("打开窗口", lambda: actions.open_dsh(settings)),
        "2": ("停止服务", lambda: "已停止" if controller.stop() else "服务未在运行"),
        "3": ("重启服务", lambda: actions.restart(settings)),
        "5": ("查看日志", lambda: str(paths.log_path())),
    }
    while True:
        print(controller.describe())
        print("\n[1] 打开窗口  [2] 停止  [3] 重启  [4] 刷新  [5] 日志路径  [0] 退出")
        choice = input("> ").strip()
        if choice in {"0", "q", ""}:
            return
        if choice in choices:
            label, work = choices[choice]
            try:
                print(work() or label)
            except Exception as exc:  # noqa: BLE001 - 菜单里只展示原因
                print(f"{type(exc).__name__}: {exc}")


def font_mode() -> str | None:
    """``cjk``：能画中文；``ascii``：只能画 ASCII；``None``：没有 Tk/显示。"""
    try:
        import tkinter as tk
        from tkinter import font as tkfont
    except Exception:  # noqa: BLE001 - 没有 tkinter
        return None
    try:
        root = tk.Tk()
        root.withdraw()
    except Exception:  # noqa: BLE001 - 没有可用显示
        return None
    try:
        return "cjk" if tkfont.nametofont("TkDefaultFont").measure("窗口") > 0 else "ascii"
    finally:
        root.destroy()


def run(settings: Settings) -> None:
    mode = font_mode()
    if mode is None:
        print("没有可用的 Tk/显示，改用终端菜单。", file=sys.stderr)
        _console_menu(settings)
        return
    if mode == "ascii":
        print("Tk 字体缺少中文字形（无 Xft），控制面板使用英文标签。", file=sys.stderr)
    Panel(settings, ascii_only=mode == "ascii").run()
