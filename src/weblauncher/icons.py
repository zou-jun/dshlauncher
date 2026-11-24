"""启动器内置图标：控制台、dsh、Jupyter 共用同一套资源定位。"""

from __future__ import annotations

import sys
from pathlib import Path

from . import paths

NAMES = ("control", "dsh", "jupyter")


def _directories() -> list[Path]:
    candidates: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "assets")
    root = paths.executable_dir()
    candidates.extend([root / "assets", root / "packaging" / "assets"])
    return candidates


def path(name: str, suffix: str) -> Path | None:
    """返回图标文件；name 只接受内置名称，避免任意路径读取。"""
    if name not in NAMES:
        raise KeyError(f"未知图标：{name}")
    for directory in _directories():
        candidate = directory / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def read(name: str) -> bytes:
    found = path(name, ".png")
    if found is None:
        raise FileNotFoundError(f"缺少图标：{name}.png")
    return found.read_bytes()


__all__ = ["NAMES", "path", "read"]
