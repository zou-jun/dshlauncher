# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：单个可执行文件（Windows 为 GUI 子系统，Linux 为普通二进制）。

- 无参数（双击 / 快捷方式）→ open
- 带参数（终端里 `dshlauncher status`）→ CLI
"""

import sys
from pathlib import Path

PROJECT = Path(SPECPATH).parent
ICON = PROJECT / "packaging" / "assets" / ("app.ico" if sys.platform == "win32" else "app.png")
ICON_ARG = str(ICON) if ICON.is_file() else None
PNG = PROJECT / "packaging" / "assets" / "app.png"

analysis = Analysis(
    [str(PROJECT / "packaging" / "entry.py")],
    pathex=[str(PROJECT / "src")],
    binaries=[],
    datas=[(str(PNG), "assets")] if PNG.is_file() else [],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "_pytest", "PyInstaller"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

gui = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="dshlauncher",
    console=False,
    icon=ICON_ARG,
)
COLLECT(
    gui,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="dshlauncher",
)
