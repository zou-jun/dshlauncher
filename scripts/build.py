"""构建并部署：PyInstaller 打包 → 同步到 app/（保留 app/.dshlauncher 运行时数据）。

用法：uv run python scripts/build.py [--skip-build]
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / ".build" / "dist"
BUILD = ROOT / ".build" / "work"
APP = ROOT / "app"
DATA_NAME = ".dshlauncher"
APP_NAME = "dshlauncher.exe" if sys.platform == "win32" else "dshlauncher"
ICON = ROOT / "packaging" / "assets" / "app.png"


def build() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD),
            str(ROOT / "packaging" / "dshlauncher.spec"),
        ],
        cwd=ROOT,
        check=True,
    )


def deploy() -> None:
    source = DIST / "dshlauncher"
    if not source.is_dir():
        raise SystemExit(f"没有找到构建产物：{source}")
    APP.mkdir(parents=True, exist_ok=True)

    try:
        _sync(source)
        if ICON.is_file():
            assets = APP / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ICON, assets / ICON.name)
    except (shutil.Error, OSError) as exc:
        raise SystemExit(
            "部署失败：目标文件被占用。先关闭 DeepSeek Harness 窗口并执行 "
            f"`{APP_NAME} stop`，再重试。\n"
            f"详细：{exc}"
        ) from exc


def _sync(source: Path) -> None:
    for item in source.iterdir():
        if item.name == DATA_NAME:
            continue
        target = APP / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    # 清理上一版遗留、本次已不存在的文件（数据目录除外）
    for item in APP.iterdir():
        if item.name == DATA_NAME or (source / item.name).exists():
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()

    print(f"已部署到 {APP}")
    exe = APP / APP_NAME
    if exe.exists():
        print(f"  {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    if "--skip-build" not in sys.argv:
        build()
    deploy()
