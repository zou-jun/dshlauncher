"""Linux 桌面入口：``.desktop`` + 图标。

桌面图标（``~/Desktop``）在 GNOME 默认配置下不显示，因此入口只写进
``~/.local/share/applications``（应用菜单里可见）；``~/Desktop`` 只做旧版清理。
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import sys
from pathlib import Path

from .. import paths

DESKTOP_NAME = "dsh"
ICON_NAME = "dshlauncher"
ICON_SIZE = 256

#: 动作 -> 文件名后缀；空后缀即默认 open。
ENTRIES = {"open": "", "ui": "-ui"}

#: 旧版本写过的位置/名字，install 与 uninstall 都顺手清理。
LEGACY_NAMES = ("dsh.desktop", "dshlauncher.desktop", "dsh-ui.desktop", "dshlauncher-ui.desktop")


def gui_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    # 不要 resolve：venv 里的 python 是指向基础解释器的符号链接，
    # 解析后会丢掉 pyvenv.cfg，从桌面启动就找不到包了。
    return [str(Path(sys.executable)), "-m", "dshlauncher"]


def working_dir() -> Path:
    return paths.executable_dir()


def data_home() -> Path:
    override = os.environ.get("XDG_DATA_HOME")
    return Path(override) if override else Path.home() / ".local" / "share"


def applications_dir() -> Path:
    return data_home() / "applications"


def icon_source() -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "assets" / "app.png")
    else:
        candidates.append(paths.executable_dir() / "packaging" / "assets" / "app.png")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def icon_path() -> Path:
    return data_home() / "icons" / "hicolor" / f"{ICON_SIZE}x{ICON_SIZE}" / "apps" / f"{ICON_NAME}.png"


def install_icon(icon: Path | None) -> Path | None:
    """把图标放进 hicolor 主题目录；显式图标只引用，不复制。"""
    if icon is not None:
        return icon.expanduser()
    source = icon_source()
    if source is None:
        return None
    target = icon_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def _entry(action: str, icon: Path | None) -> str:
    command = shlex.join([*gui_command(), action])
    label = f"{DESKTOP_NAME} 控制台" if action == "ui" else DESKTOP_NAME
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={label}",
        "Comment=托管 dsh web 服务并打开无扩展 UI 窗口",
        f"Exec={command}",
        f"Path={working_dir()}",
        f"Icon={icon}" if icon is not None else "Icon=applications-development",
        "Terminal=false",
        "Categories=Development;",
        "StartupNotify=false",
    ]
    return "\n".join(lines) + "\n"


def _desktop_dirs() -> list[Path]:
    """要清理的旧位置（GNOME 下没有桌面图标，仅兼容从前的版本）。"""
    return [Path.home() / "Desktop"]


def create(icon: Path | None = None) -> list[Path]:
    applications = applications_dir()
    applications.mkdir(parents=True, exist_ok=True)
    installed_icon = install_icon(icon)

    written: list[Path] = []
    for action, suffix in ENTRIES.items():
        path = applications / f"{DESKTOP_NAME}{suffix}.desktop"
        path.write_text(_entry(action, installed_icon), "utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        written.append(path)
    for directory in _desktop_dirs():
        for name in LEGACY_NAMES:
            legacy = directory / name
            if legacy.is_file():
                legacy.unlink()
    if icon is None and installed_icon is not None:
        written.append(installed_icon)
    return written


def remove() -> list[Path]:
    removed: list[Path] = []
    for directory in [applications_dir(), *_desktop_dirs()]:
        for name in {*LEGACY_NAMES, *(f"{DESKTOP_NAME}{suffix}.desktop" for suffix in ENTRIES.values())}:
            path = directory / name
            if path.is_file():
                path.unlink()
                removed.append(path)
    icon = icon_path()
    if icon.is_file():
        icon.unlink()
        removed.append(icon)
    return removed
