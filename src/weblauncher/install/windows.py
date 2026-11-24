"""Windows 桌面入口：生成 .lnk（不需要管理员权限）。"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from .. import icons

CREATE_NO_WINDOW = 0x08000000

#: 主入口：托盘 + 打开默认服务。每个服务再单独建一个快捷方式。
MAIN_NAME = "weblauncher.lnk"
MAIN_ICON = "control"
SERVICE_LINKS = {
    "dsh": ("dsh web.lnk", "ui dsh", "dsh"),
    "jupyter": ("Jupyter Lab.lnk", "ui jupyter", "jupyter"),
}

#: 改名前的旧快捷方式：install / uninstall 都顺手清掉，避免桌面上留两套
LEGACY_NAMES = (
    "dshlauncher.lnk",
    "dsh.lnk",
    "DeepSeek Harness.lnk",
    "DeepSeek Harness 控制台.lnk",
    "dsh 控制台.lnk",
)


def gui_command() -> tuple[Path, str]:
    """(可执行文件, 附加参数)。冻结时是窗口化 exe；源码运行时是 pythonw -m。"""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return exe, ""
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    return interpreter, "-m weblauncher"


def _run_powershell(script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "powershell 执行失败")
    return result.stdout


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _icon_location(name: str, custom: Path | None, exe: Path) -> str:
    if custom is not None:
        return f"{custom},0"
    found = icons.path(name, ".ico")
    if found is not None:
        return f"{found},0"
    if getattr(sys, "frozen", False):
        return f"{exe},0"  # PyInstaller 内嵌图标
    return ""


def create(
    icon: Path | None = None,
    *,
    services: tuple[str, ...] | list[str] = ("dsh", "jupyter"),
) -> list[Path]:
    exe, prefix = gui_command()

    lines = [
        "$ErrorActionPreference='Stop'",
        "$desktop=[Environment]::GetFolderPath('Desktop')",
        "$shell=New-Object -ComObject WScript.Shell",
        "function New-Link([string]$name,[string]$arguments,[string]$icon){",
        "  $path=Join-Path $desktop $name",
        "  $link=$shell.CreateShortcut($path)",
        f"  $link.TargetPath={_ps_quote(str(exe))}",
        "  $link.Arguments=$arguments",
        f"  $link.WorkingDirectory={_ps_quote(str(exe.parent))}",
        "  $link.IconLocation=$icon",
        "  $link.Save()",
        "  Write-Output $path",
        "}",
    ]
    for name in LEGACY_NAMES:
        lines.append(f"$old=Join-Path $desktop {_ps_quote(name)}")
        lines.append("if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force }")

    links: dict[str, tuple[str, str]] = {MAIN_NAME: ("ui", MAIN_ICON)}
    for service in services:
        entry = SERVICE_LINKS.get(service)
        if entry is not None:
            links[entry[0]] = (entry[1], entry[2])
    for name, (arguments, icon_name) in links.items():
        location = _icon_location(icon_name, icon, exe)
        lines.append(
            f"New-Link {_ps_quote(name)} {_ps_quote(f'{prefix} {arguments}'.strip())} {_ps_quote(location)}"
        )

    output = _run_powershell("\n".join(lines))
    return [Path(line.strip()) for line in output.splitlines() if line.strip()]


def remove() -> list[Path]:
    names = {MAIN_NAME, *(link[0] for link in SERVICE_LINKS.values()), *LEGACY_NAMES}
    lines = [
        "$ErrorActionPreference='Stop'",
        "$desktop=[Environment]::GetFolderPath('Desktop')",
    ]
    for name in names:
        lines.append(f"$path=Join-Path $desktop {_ps_quote(name)}")
        lines.append(
            "if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force; Write-Output $path }"
        )
    output = _run_powershell("\n".join(lines))
    return [Path(line.strip()) for line in output.splitlines() if line.strip()]
