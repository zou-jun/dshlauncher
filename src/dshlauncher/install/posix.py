"""Linux / macOS 桌面入口（尽力而为，未在真机验证）。"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

DESKTOP_NAME = "dsh"


def gui_command() -> list[str]:
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return [str(exe)]
    return [str(exe), "-m", "dshlauncher"]


def _entry(action: str, icon: Path | None) -> str:
    command = " ".join([*gui_command(), action])
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={DESKTOP_NAME}{' 控制台' if action == 'ui' else ''}",
        "Comment=托管 dsh web 服务并打开无扩展 UI 窗口",
        f"Exec={command}",
        "Terminal=false",
        "Categories=Development;",
    ]
    if icon is not None:
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n"


def _targets() -> list[Path]:
    home = Path.home()
    apps = home / ".local" / "share" / "applications"
    desktop = home / "Desktop"
    return [apps, desktop]


def create(icon: Path | None = None) -> list[Path]:
    written: list[Path] = []
    for directory in _targets():
        directory.mkdir(parents=True, exist_ok=True)
        for action, suffix in (("open", ""), ("ui", "-ui")):
            path = directory / f"dsh{suffix}.desktop"
            path.write_text(_entry(action, icon), "utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
            written.append(path)
    return written


def remove() -> list[Path]:
    removed: list[Path] = []
    for directory in _targets():
        for stem in ("dsh", "dshlauncher"):  # 旧前缀一并清理
            for suffix in ("", "-ui"):
                path = directory / f"{stem}{suffix}.desktop"
                if path.is_file():
                    path.unlink()
                    removed.append(path)
    return removed
