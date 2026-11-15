"""macOS / 其它 POSIX 桌面入口：不自动创建，避免写入 macOS 不识别的 .desktop。"""

from __future__ import annotations

import sys
from pathlib import Path

DESKTOP_NAME = "dsh"


def gui_command() -> list[str]:
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return [str(exe)]
    return [str(exe), "-m", "dshlauncher"]


def _targets() -> list[Path]:
    home = Path.home()
    return [home / ".local" / "share" / "applications", home / "Desktop"]


def create(icon: Path | None = None) -> list[Path]:
    command = " ".join([*gui_command(), "tray"])
    raise RuntimeError(
        "macOS / 其它 POSIX 暂不支持自动创建桌面入口；"
        f"请手动运行 `{command}`，或在 Finder 里为可执行文件创建别名。"
    )


def remove() -> list[Path]:
    """清理旧版本在 POSIX 上写过的 .desktop 文件。"""
    removed: list[Path] = []
    for directory in _targets():
        for stem in ("dsh", "dshlauncher"):
            for suffix in ("", "-ui"):
                path = directory / f"{stem}{suffix}.desktop"
                if path.is_file():
                    path.unlink()
                    removed.append(path)
    return removed
