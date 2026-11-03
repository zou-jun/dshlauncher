"""平台后端契约。

每个后端模块（`windows` / `linux` / `posix`）都提供下面这些模块级函数：

- ``detach_kwargs()``：传给 ``subprocess.Popen`` 的分离参数
- ``process_names(family)``：该浏览器家族的进程名集合
- ``work_area()``：主显示器工作区，无法获取时返回 ``None``
- ``find_window(pids)``：这些进程里最大的可见顶层窗口，没有则 ``None``
- ``window_rect(hwnd)`` / ``apply_rect(hwnd, rect)``：读写窗口矩形
- ``is_minimized(hwnd)`` / ``present(hwnd)``：最小化判定与置前
- ``open_path(path)``：用系统默认程序打开文件
- ``supports_window_control(ozone)``：当前会话能否枚举/移动/置前窗口

Linux 由 ``linux`` 后端用 X11/EWMH 实现；原生 Wayland 下返回 False，
窗口尺寸交给 Chromium 的 ``--window-size``。macOS 的 ``posix`` 后端全是空操作。
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..geometry import Rect


class Backend(Protocol):
    def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]: ...

    def process_names(self, browser: str) -> set[str]: ...

    def supports_window_control(self, ozone: str | None = None) -> bool: ...

    def work_area(self) -> Rect | None: ...

    def find_window(self, pids: set[int]) -> int | None: ...

    def window_rect(self, hwnd: int) -> Rect | None: ...

    def apply_rect(self, hwnd: int, rect: Rect) -> None: ...

    def is_minimized(self, hwnd: int) -> bool: ...

    def present(self, hwnd: int) -> None: ...

    def open_path(self, path: Path) -> None: ...


__all__ = ["Backend", "Rect"]
