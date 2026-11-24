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

from .. import icons, paths

MAIN_NAME = "weblauncher.desktop"
MAIN_ICON = "control"
SERVICE_ENTRIES = {
    "dsh": ("dsh web", "ui dsh", "dsh"),
    "jupyter": ("Jupyter Lab", "ui jupyter", "jupyter"),
}
ICON_SIZE = 256
ICON_NAMES = ("control", "dsh", "jupyter")

#: 旧版本写过的位置/名字，install 与 uninstall 都顺手清理。
LEGACY_NAMES = (
    "dsh.desktop",
    "dshlauncher.desktop",
    "dsh-ui.desktop",
    "dshlauncher-ui.desktop",
)


def gui_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    # 不要 resolve：venv 里的 python 是指向基础解释器的符号链接，
    # 解析后会丢掉 pyvenv.cfg，从桌面启动就找不到包了。
    return [str(Path(sys.executable)), "-m", "weblauncher"]


def working_dir() -> Path:
    return paths.executable_dir()


def data_home() -> Path:
    override = os.environ.get("XDG_DATA_HOME")
    return Path(override) if override else Path.home() / ".local" / "share"


def applications_dir() -> Path:
    return data_home() / "applications"


def icon_source(name: str) -> Path | None:
    return icons.path(name, ".png")


def icon_path(name: str) -> Path:
    return data_home() / "icons" / "hicolor" / f"{ICON_SIZE}x{ICON_SIZE}" / "apps" / f"weblauncher-{name}.png"


def install_icons(icon: Path | None) -> dict[str, Path | None]:
    """把内置图标放进 hicolor 主题目录；显式图标只引用，不复制。"""
    if icon is not None:
        shared = icon.expanduser()
        return {name: shared for name in ICON_NAMES}
    installed: dict[str, Path | None] = {}
    for name in ICON_NAMES:
        source = icon_source(name)
        if source is None:
            installed[name] = None
            continue
        target = icon_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        installed[name] = target
    return installed


def _entry(label: str, action: str, icon: Path | None) -> str:
    command = shlex.join([*gui_command(), action])
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={label}",
        "Comment=托管本地服务并打开独立窗口",
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


def create(
    icon: Path | None = None, *, services: tuple[str, ...] | list[str] = ("dsh", "jupyter")
) -> list[Path]:
    applications = applications_dir()
    applications.mkdir(parents=True, exist_ok=True)
    installed_icons = install_icons(icon)
    for directory in [applications, *_desktop_dirs()]:
        for name in LEGACY_NAMES:
            legacy = directory / name
            if legacy.is_file():
                legacy.unlink()

    entries: dict[str, tuple[str, str, str]] = {MAIN_NAME: ("Web 服务启动器", "ui", MAIN_ICON)}
    for service in services:
        entry = SERVICE_ENTRIES.get(service)
        if entry is not None:
            entries[f"{service}.desktop"] = entry

    written: list[Path] = []
    for filename, (label, action, icon_name) in entries.items():
        path = applications / filename
        path.write_text(_entry(label, action, installed_icons.get(icon_name)), "utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        written.append(path)
    if icon is None:
        written.extend(item for item in installed_icons.values() if item is not None)
    return written


def remove() -> list[Path]:
    removed: list[Path] = []
    names = {MAIN_NAME, *LEGACY_NAMES, *(f"{service}.desktop" for service in SERVICE_ENTRIES)}
    for directory in [applications_dir(), *_desktop_dirs()]:
        for name in names:
            path = directory / name
            if path.is_file():
                path.unlink()
                removed.append(path)
    for name in ICON_NAMES:
        icon = icon_path(name)
        if icon.is_file():
            icon.unlink()
            removed.append(icon)
    old_icon = data_home() / "icons" / "hicolor" / f"{ICON_SIZE}x{ICON_SIZE}" / "apps" / "weblauncher.png"
    if old_icon.is_file():
        old_icon.unlink()
        removed.append(old_icon)
    return removed
