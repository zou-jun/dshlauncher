"""平台后端选择：Windows 完整实现、Linux X11、其余平台尽力而为。"""

from __future__ import annotations

import os
import sys
from types import ModuleType

BACKENDS = ("windows", "linux", "posix")


def load() -> ModuleType:
    """按平台加载后端；``DSHLAUNCHER_WINDOW_BACKEND`` 可强制覆盖（测试/排障）。"""
    override = os.environ.get("DSHLAUNCHER_WINDOW_BACKEND", "").strip().lower()
    if override in BACKENDS:
        return _import(override)
    if sys.platform == "win32":
        return _import("windows")
    if sys.platform.startswith("linux"):
        return _import("linux")
    return _import("posix")


def _import(name: str) -> ModuleType:
    if name == "windows":
        from . import windows as backend
    elif name == "linux":
        from . import linux as backend
    else:
        from . import posix as backend
    return backend


__all__ = ["BACKENDS", "load"]
