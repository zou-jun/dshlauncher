"""Windows 后端：分离进程 + Win32 窗口查找 / 几何 / 置前。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

from ..geometry import Rect

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

SW_RESTORE = 9
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
GW_OWNER = 4
SPI_GETWORKAREA = 0x0030

_PROCESS_NAME = {
    "chrome": "chrome.exe",
    "chromium": "chromium.exe",
    "edge": "msedge.exe",
    "brave": "brave.exe",
}


def detach_kwargs(*, breakaway: bool = True) -> dict[str, int]:
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    if breakaway:
        flags |= CREATE_BREAKAWAY_FROM_JOB
    return {"creationflags": flags}


def process_names(browser: str) -> set[str]:
    name = _PROCESS_NAME.get(browser)
    return {name} if name else set(_PROCESS_NAME.values())


def supports_window_control(ozone: str | None = None) -> bool:
    return True


def _user32() -> ctypes.WinDLL:
    return ctypes.WinDLL("user32", use_last_error=True)


def work_area() -> Rect | None:
    rect = wintypes.RECT()
    if not _user32().SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return None
    return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def window_rect(hwnd: int) -> Rect | None:
    rect = wintypes.RECT()
    if not _user32().GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def find_window(pids: set[int]) -> int | None:
    """属于这些进程的最大可见顶层窗口（Chrome 会附带若干 0 尺寸辅助窗口）。"""
    if not pids:
        return None
    user32 = _user32()
    candidates: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):  # noqa: ANN001 - ctypes 回调签名
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = (rect.right - rect.left) * (rect.bottom - rect.top)
            if area > 0:
                candidates.append((area, hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return max(candidates)[1] if candidates else None


def apply_rect(hwnd: int, rect: Rect) -> None:
    _user32().SetWindowPos(
        hwnd,
        None,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        SWP_NOZORDER | SWP_NOACTIVATE,
    )


def is_minimized(hwnd: int) -> bool:
    return bool(_user32().IsIconic(hwnd))


def present(hwnd: int) -> None:
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)


def open_path(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606 - 交给系统默认程序
