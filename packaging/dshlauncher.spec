# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：单个窗口化 exe。

- 无参数（双击 / 快捷方式）→ open，不闪黑窗
- 带参数（终端里 `dshlauncher.exe status`）→ CLI，进程启动时接管父控制台输出
"""

from pathlib import Path

PROJECT = Path(SPECPATH).parent
ICON = PROJECT / "packaging" / "assets" / "app.ico"
ICON_ARG = str(ICON) if ICON.is_file() else None

analysis = Analysis(
    [str(PROJECT / "packaging" / "entry.py")],
    pathex=[str(PROJECT / "src")],
    binaries=[],
    datas=[],
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
