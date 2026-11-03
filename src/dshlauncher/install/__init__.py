"""桌面入口安装：按平台选择实现。"""

from __future__ import annotations

import sys
from pathlib import Path


def _impl():
    if sys.platform == "win32":
        from . import windows

        return windows
    if sys.platform.startswith("linux"):
        from . import linux

        return linux
    from . import posix

    return posix


def create(icon: Path | None = None) -> list[Path]:
    """创建桌面入口，返回实际写入的路径。"""
    return _impl().create(icon)


def remove() -> list[Path]:
    """删除桌面入口，返回实际删除的路径。"""
    return _impl().remove()
