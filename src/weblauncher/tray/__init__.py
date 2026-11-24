"""常驻托盘入口。

业务命令已经迁到 Web 控制台；``tray`` 只保留最小图标、单实例 IPC 和
控制台启动入口。``app`` 里的符号按需导入，避免 ``control`` 与 ``tray``
在包初始化阶段互相循环依赖。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
    send_ui,
)
from .single import LOCK_NAME, Lock, acquire_lock, release_lock

if TYPE_CHECKING:
    from .app import ICON_SIZE, TITLE, TrayApp, icon_image, open_console_url, run

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
    "open_console_url",
    "release_lock",
    "run",
    "running",
    "send_open",
    "send_ui",
    "state_text",
    "status_text",
]

_APP_SYMBOLS = {"ICON_SIZE", "TITLE", "TrayApp", "icon_image", "open_console_url", "run"}


def __getattr__(name: str) -> Any:
    if name in _APP_SYMBOLS:
        from . import app as app_module

        return getattr(app_module, name)
    raise AttributeError(name)
