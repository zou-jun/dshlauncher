"""POSIX 后端（Linux / macOS）：分离进程可用，窗口控制尽力而为。

没有 Win32 那样的窗口枚举/定位 API，因此 ``find_window`` / ``work_area`` /
``apply_rect`` / ``present`` 都是空操作；窗口尺寸交给 Chromium 的
``--window-size`` / ``--window-position`` 参数，去重退化为"已有进程就复用"。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from ..geometry import Rect

_PROCESS_NAME = {
    "chrome": "chrome",
    "chromium": "chromium",
    "edge": "microsoft-edge",
    "brave": "brave-browser",
}


def detach_kwargs(*, breakaway: bool = True) -> dict[str, bool]:
    # 新会话 = 脱离当前终端/进程组，终端关闭不会带走子进程。
    return {"start_new_session": True}


def process_names(browser: str) -> set[str]:
    name = _PROCESS_NAME.get(browser)
    return {name} if name else set(_PROCESS_NAME.values())


def work_area() -> Rect | None:
    return None


def find_window(pids: set[int]) -> int | None:
    return None


def window_rect(hwnd: int) -> Rect | None:
    return None


def apply_rect(hwnd: int, rect: Rect) -> None:
    return None


def is_minimized(hwnd: int) -> bool:
    return False


def present(hwnd: int) -> None:
    return None


def open_path(path: Path) -> None:
    opener = "open" if sys.platform == "darwin" else (shutil.which("xdg-open") or "xdg-open")
    subprocess.Popen([opener, str(path)])
