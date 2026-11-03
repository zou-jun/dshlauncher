"""Linux 后端：分离进程 + X11/EWMH 窗口控制（ctypes 直连 libX11）。

窗口控制只在 X11 窗口上成立：
- X11 会话：Chrome 默认就是 X11 客户端，直接可用
- Wayland 会话：Chrome 默认原生 Wayland，X11 树里看不到窗口；此时若
  ``ozone=x11``（Chrome 走 XWayland），窗口枚举/移动/置前都可用（GNOME 实测）

原生 Wayland 下 ``supports_window_control`` 返回 False，调用方跳过窗口操作。
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

from ..geometry import Rect

_PROCESS_NAME = {
    "chrome": "chrome",
    "chromium": "chromium",
    "edge": "microsoft-edge",
    "brave": "brave-browser",
}

XA_WINDOW = 33
CLIENT_MESSAGE = 33
SUBSTRUCTURE_NOTIFY = 0x00080000
SUBSTRUCTURE_REDIRECT = 0x00100000
IS_VIEWABLE = 2

#: Wayland 会话里只有显式走 XWayland 才能控制窗口。
X11_OZONE = "x11"


class _WindowAttributes(ctypes.Structure):
    """Xlib ``XWindowAttributes``。"""

    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


class _ClientMessage(ctypes.Structure):
    """Xlib ``XClientMessageEvent``。"""

    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class _X11:
    """最小化的 libX11 绑定（只用到的那几个函数）。"""

    def __init__(self) -> None:
        name = ctypes.util.find_library("X11")
        if name is None:
            raise OSError("找不到 libX11")
        lib = ctypes.CDLL(name)
        self.lib = lib

        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultScreen.restype = ctypes.c_int
        lib.XDefaultScreen.argtypes = [ctypes.c_void_p]
        lib.XDisplayWidth.restype = ctypes.c_int
        lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XDisplayHeight.restype = ctypes.c_int
        lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]

        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XGetWindowProperty.restype = ctypes.c_int
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        lib.XFree.argtypes = [ctypes.c_void_p]

        lib.XGetWindowAttributes.restype = ctypes.c_int
        lib.XGetWindowAttributes.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_WindowAttributes),
        ]
        lib.XTranslateCoordinates.restype = ctypes.c_int
        lib.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        lib.XMoveResizeWindow.restype = ctypes.c_int
        lib.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        lib.XRaiseWindow.restype = ctypes.c_int
        lib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XMapRaised.restype = ctypes.c_int
        lib.XMapRaised.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XFlush.restype = ctypes.c_int
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XSendEvent.restype = ctypes.c_int
        lib.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        lib.XSetErrorHandler.restype = ctypes.c_void_p
        lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]

        # 窗口可能随时消失；默认错误处理器会往 stderr 打 "X Error"。
        self._handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda *_: 0)
        lib.XSetErrorHandler(ctypes.cast(self._handler, ctypes.c_void_p))
        self._atoms: dict[tuple[int, str], int] = {}


_x11_instance: _X11 | None = None


def _x11() -> _X11:
    global _x11_instance
    if _x11_instance is None:
        _x11_instance = _X11()
    return _x11_instance


@contextlib.contextmanager
def _display() -> Iterator[tuple[_X11, int]]:
    x = _x11()
    display = x.lib.XOpenDisplay(None)
    if not display:
        raise OSError("无法连接 X 显示")
    try:
        yield x, display
    finally:
        x.lib.XCloseDisplay(display)


def _atom(x: _X11, display: int, name: str) -> int:
    key = (display, name)
    cached = x._atoms.get(key)
    if cached is not None:
        return cached
    value = int(x.lib.XInternAtom(display, name.encode(), 0))
    x._atoms[key] = value
    return value


def _property(x: _X11, display: int, window: int, name: str, req_type: int = 0) -> bytes:
    """读一个属性并统一成小端字节串（32 位项按 4 字节、8 位项原样）。"""
    atom = _atom(x, display, name)
    actual_type = ctypes.c_ulong()
    fmt = ctypes.c_int()
    count = ctypes.c_ulong()
    remaining = ctypes.c_ulong()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    status = x.lib.XGetWindowProperty(
        display,
        window,
        atom,
        0,
        4096,
        0,
        req_type,
        ctypes.byref(actual_type),
        ctypes.byref(fmt),
        ctypes.byref(count),
        ctypes.byref(remaining),
        ctypes.byref(data),
    )
    if status != 0 or not data or count.value == 0:
        if data:
            x.lib.XFree(data)
        return b""
    try:
        if fmt.value == 32:
            longs = ctypes.cast(data, ctypes.POINTER(ctypes.c_long))
            raw = b"".join(
                int(longs[index] & 0xFFFFFFFF).to_bytes(4, "little") for index in range(count.value)
            )
        elif fmt.value == 16:
            shorts = ctypes.cast(data, ctypes.POINTER(ctypes.c_short))
            raw = b"".join(int(shorts[index] & 0xFFFF).to_bytes(2, "little") for index in range(count.value))
        else:
            raw = ctypes.string_at(data, count.value)
    finally:
        x.lib.XFree(data)
    return raw


def _number_values(raw: bytes) -> list[int]:
    return [int.from_bytes(raw[index : index + 4], "little") for index in range(0, len(raw) - 3, 4)]


def _attributes(x: _X11, display: int, window: int) -> _WindowAttributes | None:
    attrs = _WindowAttributes()
    if x.lib.XGetWindowAttributes(display, window, ctypes.byref(attrs)) == 0:
        return None
    return attrs


def _client_list(x: _X11, display: int) -> list[int]:
    root = int(x.lib.XDefaultRootWindow(display))
    return _number_values(_property(x, display, root, "_NET_CLIENT_LIST", XA_WINDOW))


def _window_pid(x: _X11, display: int, window: int) -> int | None:
    values = _number_values(_property(x, display, window, "_NET_WM_PID"))
    return values[0] if values else None


def _window_states(x: _X11, display: int, window: int) -> set[str]:
    raw = _property(x, display, window, "_NET_WM_STATE")
    names: set[str] = set()
    for value in _number_values(raw):
        # 反向映射 atom -> 名字代价高，这里只比较我们关心的两个。
        if value == _atom(x, display, "_NET_WM_STATE_HIDDEN"):
            names.add("hidden")
        elif value == _atom(x, display, "_NET_WM_STATE_FULLSCREEN"):
            names.add("fullscreen")
    return names


def _send_client_message(
    x: _X11, display: int, target: int, window: int, message: str, data: list[int]
) -> None:
    event = ctypes.create_string_buffer(192)  # sizeof(XEvent)
    message_event = ctypes.cast(event, ctypes.POINTER(_ClientMessage)).contents
    message_event.type = CLIENT_MESSAGE
    message_event.send_event = 1
    message_event.display = ctypes.c_void_p(display)
    message_event.window = window
    message_event.message_type = _atom(x, display, message)
    message_event.format = 32
    for index, value in enumerate(data[:5]):
        message_event.data[index] = value
    x.lib.XSendEvent(
        display,
        target,
        0,
        SUBSTRUCTURE_REDIRECT | SUBSTRUCTURE_NOTIFY,
        ctypes.byref(message_event),
    )


def _work_area_values(raw: bytes, desktop: int) -> Rect | None:
    """``_NET_WORKAREA`` 是每个桌面 4 个值（x, y, width, height）。"""
    values = _number_values(raw)
    if len(values) >= 4 * (desktop + 1):
        values = values[4 * desktop : 4 * desktop + 4]
    elif len(values) < 4:
        return None
    else:
        values = values[:4]
    rect = Rect(*values)
    return rect if rect.width > 0 and rect.height > 0 else None


# ── 后端契约 ──────────────────────────────────────────────────────────
def detach_kwargs(*, breakaway: bool = True) -> dict[str, bool]:
    # 新会话 = 脱离终端/进程组，终端关闭不会带走子进程。
    return {"start_new_session": True}


def process_names(browser: str) -> set[str]:
    name = _PROCESS_NAME.get(browser)
    return {name} if name else set(_PROCESS_NAME.values())


def display_available() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        with _display():
            return True
    except OSError:
        return False


def supports_window_control(ozone: str | None = None) -> bool:
    """当前会话里能否用 X11 控制 Chrome 窗口。"""
    if not display_available():
        return False
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )
    if not wayland:
        return True
    return (ozone or "").strip().lower() == X11_OZONE


def work_area() -> Rect | None:
    try:
        with _display() as (x, display):
            root = int(x.lib.XDefaultRootWindow(display))
            desktop_values = _number_values(_property(x, display, root, "_NET_CURRENT_DESKTOP"))
            desktop = desktop_values[0] if desktop_values else 0
            rect = _work_area_values(_property(x, display, root, "_NET_WORKAREA"), desktop)
            if rect is not None:
                return rect
            screen = x.lib.XDefaultScreen(display)
            return Rect(
                0,
                0,
                int(x.lib.XDisplayWidth(display, screen)),
                int(x.lib.XDisplayHeight(display, screen)),
            )
    except OSError:
        return None


def find_window(pids: set[int]) -> int | None:
    """属于这些进程的最大可见顶层窗口（Chrome 会附带若干辅助窗口）。"""
    if not pids:
        return None
    try:
        with _display() as (x, display):
            best: tuple[int, int] | None = None
            for window in _client_list(x, display):
                if _window_pid(x, display, window) not in pids:
                    continue
                attrs = _attributes(x, display, window)
                if attrs is None or attrs.map_state != IS_VIEWABLE:
                    continue
                if attrs.width <= 0 or attrs.height <= 0:
                    continue
                area = attrs.width * attrs.height
                if best is None or area > best[0]:
                    best = (area, window)
            return best[1] if best is not None else None
    except OSError:
        return None


def window_rect(hwnd: int) -> Rect | None:
    try:
        with _display() as (x, display):
            attrs = _attributes(x, display, hwnd)
            if attrs is None:
                return None
            root = int(x.lib.XDefaultRootWindow(display))
            x_pos = ctypes.c_int()
            y_pos = ctypes.c_int()
            child = ctypes.c_ulong()
            if (
                x.lib.XTranslateCoordinates(
                    display, hwnd, root, 0, 0, ctypes.byref(x_pos), ctypes.byref(y_pos), ctypes.byref(child)
                )
                == 0
            ):
                return None
            return Rect(x_pos.value, y_pos.value, attrs.width, attrs.height)
    except OSError:
        return None


def apply_rect(hwnd: int, rect: Rect) -> None:
    try:
        with _display() as (x, display):
            x.lib.XMoveResizeWindow(display, hwnd, rect.x, rect.y, rect.width, rect.height)
            x.lib.XFlush(display)
    except OSError:
        return


def is_minimized(hwnd: int) -> bool:
    try:
        with _display() as (x, display):
            if "hidden" in _window_states(x, display, hwnd):
                return True
            attrs = _attributes(x, display, hwnd)
            return attrs is not None and attrs.map_state != IS_VIEWABLE
    except OSError:
        return False


def present(hwnd: int) -> None:
    try:
        with _display() as (x, display):
            root = int(x.lib.XDefaultRootWindow(display))
            attrs = _attributes(x, display, hwnd)
            if attrs is not None and attrs.map_state != IS_VIEWABLE:
                x.lib.XMapRaised(display, hwnd)
            _send_client_message(
                x,
                display,
                root,
                hwnd,
                "_NET_ACTIVE_WINDOW",
                [1, 0, 0],  # source=application, timestamp=CURRENT_TIME, requestor=none
            )
            x.lib.XRaiseWindow(display, hwnd)
            x.lib.XFlush(display)
    except OSError:
        return


def open_path(path: Path) -> None:
    "用系统默认程序打开文件。"
    opener = "open" if sys.platform == "darwin" else (shutil.which("xdg-open") or "xdg-open")
    subprocess.Popen([opener, str(path)])
