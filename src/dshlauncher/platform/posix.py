"""macOS 后端：分离进程可用，窗口控制不可用。

Linux 走 ``linux`` 后端（X11/EWMH）；这里只处理 macOS：没有等价的窗口
枚举/定位 API，因此 ``find_window`` / ``work_area`` / ``apply_rect`` /
``present`` 都是空操作，窗口尺寸交给 Chromium 的 ``--window-size``。
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


def supports_window_control(ozone: str | None = None) -> bool:
    return False


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
