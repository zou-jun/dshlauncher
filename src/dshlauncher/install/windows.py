"""Windows 桌面入口：生成 .lnk（不需要管理员权限）。"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

#: 动作 -> 快捷方式文件名（短名，桌面上不占地方）
LINK_NAMES = {
    "open": "dsh.lnk",
    "ui": "dsh 控制台.lnk",
}

#: 改名前的旧快捷方式：install / uninstall 都顺手清掉，避免桌面上留两套
LEGACY_NAMES = (
    "DeepSeek Harness.lnk",
    "DeepSeek Harness 控制台.lnk",
)


def gui_command() -> tuple[Path, str]:
    """(可执行文件, 附加参数)。冻结时是窗口化 exe；源码运行时是 pythonw -m。"""
    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return exe, ""
    pythonw = exe.with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else exe
    return interpreter, "-m dshlauncher"


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


def create(icon: Path | None = None) -> list[Path]:
    exe, prefix = gui_command()
    if icon is not None:
        icon_location = f"{icon},0"
    elif getattr(sys, "frozen", False):
        icon_location = f"{exe},0"  # PyInstaller 内嵌图标
    else:
        icon_location = ""

    lines = [
        "$ErrorActionPreference='Stop'",
        "$desktop=[Environment]::GetFolderPath('Desktop')",
        "$shell=New-Object -ComObject WScript.Shell",
        "function New-Link([string]$name,[string]$arguments){",
        "  $path=Join-Path $desktop $name",
        "  $link=$shell.CreateShortcut($path)",
        f"  $link.TargetPath={_ps_quote(str(exe))}",
        "  $link.Arguments=$arguments",
        f"  $link.WorkingDirectory={_ps_quote(str(exe.parent))}",
        f"  $link.IconLocation={_ps_quote(icon_location)}",
        "  $link.Save()",
        "  Write-Output $path",
        "}",
    ]
    for name in LEGACY_NAMES:
        lines.append(f"$old=Join-Path $desktop {_ps_quote(name)}")
        lines.append("if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force }")

    for action, name in LINK_NAMES.items():
        lines.append(f"New-Link {_ps_quote(name)} {_ps_quote(f'{prefix} {action}'.strip())}")

    output = _run_powershell("\n".join(lines))
    return [Path(line.strip()) for line in output.splitlines() if line.strip()]


def remove() -> list[Path]:
    lines = [
        "$ErrorActionPreference='Stop'",
        "$desktop=[Environment]::GetFolderPath('Desktop')",
    ]
    for name in (*LINK_NAMES.values(), *LEGACY_NAMES):
        lines.append(f"$path=Join-Path $desktop {_ps_quote(name)}")
        lines.append(
            "if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force; Write-Output $path }"
        )
    output = _run_powershell("\n".join(lines))
    return [Path(line.strip()) for line in output.splitlines() if line.strip()]
