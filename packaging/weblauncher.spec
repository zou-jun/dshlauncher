# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：单个可执行文件（Windows 为 GUI 子系统，Linux 为普通二进制）。

- 无参数（双击 / 快捷方式）→ tray：打开窗口并常驻托盘
- 带参数（终端里 `weblauncher status`）→ CLI
"""

import sys
from pathlib import Path

PROJECT = Path(SPECPATH).parent
ICON = PROJECT / "packaging" / "assets" / ("app.ico" if sys.platform == "win32" else "app.png")
ICON_ARG = str(ICON) if ICON.is_file() else None
PNG = PROJECT / "packaging" / "assets" / "app.png"

# pystray 的 hook 会收集全部后端；排除其它平台用不到的，减少无效依赖与警告。
EXCLUDES = ["pytest", "_pytest", "PyInstaller", "tkinter", "_tkinter", "turtle"]
if sys.platform == "win32":
    EXCLUDES += ["pystray._gtk", "pystray._appindicator", "pystray._xorg", "pystray._darwin"]
elif sys.platform == "darwin":
    EXCLUDES += ["pystray._win32", "pystray._gtk", "pystray._appindicator", "pystray._xorg"]
else:
    EXCLUDES += ["pystray._win32", "pystray._darwin"]

analysis = Analysis(
    [str(PROJECT / "packaging" / "entry.py")],
    pathex=[str(PROJECT / "src")],
    binaries=[],
    datas=[(str(PNG), "assets")] if PNG.is_file() else [],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(analysis.pure)

gui = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="weblauncher",
    console=False,
    icon=ICON_ARG,
)
COLLECT(
    gui,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="weblauncher",
)
