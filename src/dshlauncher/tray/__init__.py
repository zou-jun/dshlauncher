"""系统托盘：双击后的常驻入口。

- ``run``：有托盘就投递打开窗口，没有就自己成为托盘；
- ``single``：pid + create_time 单实例锁；
- ``ipc``：loopback + token 的本地请求；
- ``controller``：动作与并发状态（不依赖 pystray）；
- ``app``：pystray 图标/菜单与线程调度。
"""

from __future__ import annotations

from .app import ICON_SIZE, TITLE, TrayApp, icon_image, run
from .controller import TrayController, state_text, status_text
from .ipc import (
    INFO_NAME,
    START_WAIT,
    IpcServer,
    TrayUnavailable,
    _clear_info,
    _read_info,
    _request,
    _write_info,
    running,
    send_open,
)
from .single import LOCK_NAME, Lock, acquire_lock, release_lock

__all__ = [
    "ICON_SIZE",
    "INFO_NAME",
    "LOCK_NAME",
    "START_WAIT",
    "TITLE",
    "IpcServer",
    "Lock",
    "TrayApp",
    "TrayController",
    "TrayUnavailable",
    "_clear_info",
    "_read_info",
    "_request",
    "_write_info",
    "acquire_lock",
    "icon_image",
    "release_lock",
    "run",
    "running",
    "send_open",
    "state_text",
    "status_text",
]
