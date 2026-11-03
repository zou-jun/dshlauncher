"""tkinter 控制面板（缺 tk 时降级为终端菜单）：状态 + 打开 / 停止 / 重启。"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

from . import actions, paths, platform, service
from .settings import Settings


class Panel:
    def __init__(self, settings: Settings) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.settings = settings
        self.controller = service.Service(settings)
        self.root = tk.Tk()
        self.root.title("DeepSeek Harness 控制台")
        self.root.geometry("680x340")
        self.root.minsize(560, 300)

        self._results: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._busy = False

        self._status = tk.StringVar(value="读取状态…")
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
        for text, handler in (
            ("打开窗口", self._open),
            ("停止服务", self._stop),
            ("重启服务", self._restart),
            ("刷新", self.refresh),
            ("查看日志", self._log),
            ("关闭", self.root.destroy),
        ):
            button = ttk.Button(bar, text=text, command=handler)
            button.pack(side="left", padx=(0, 8))
            self._buttons.append(button)

        self.refresh()
        self.root.bind("<Configure>", self._on_configure)
        self.root.after(120, self._drain)

    def run(self) -> None:
        self.root.mainloop()

    def refresh(self) -> None:
        self._status.set(self.controller.describe())

    def _on_configure(self, event) -> None:  # noqa: ANN001 - tkinter 事件
        if event.widget is self.root:
            self._label.configure(wraplength=max(240, int(event.width) - 40))

    def _open(self) -> None:
        self._submit("启动并打开窗口", lambda: actions.open_dsh(self.settings))

    def _stop(self) -> None:
        self._submit("停止服务", lambda: "已停止" if self.controller.stop() else "服务未在运行")

    def _restart(self) -> None:
        self._submit("重启服务", lambda: actions.restart(self.settings))

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
        self._status.set(f"{label}…")
        threading.Thread(target=self._run_work, args=(work,), daemon=True).start()

    def _run_work(self, work: Callable[[], Any]) -> None:
        try:
            self._results.put(("ok", work()))
        except Exception as exc:  # noqa: BLE001 - 面板统一展示失败原因
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
                    messagebox.showerror("操作失败", str(payload), parent=self.root)
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


def run(settings: Settings) -> None:
    try:
        import tkinter  # noqa: F401 - 只探测可用性
    except Exception:  # noqa: BLE001 - 没有 tkinter 就用终端菜单
        _console_menu(settings)
        return
    Panel(settings).run()
