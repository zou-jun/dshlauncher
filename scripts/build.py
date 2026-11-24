"""构建并部署：PyInstaller 打包 → 同步到 app/（保留 app/.weblauncher 运行时数据）。

用法：uv run python scripts/build.py [--skip-build]
"""

from __future__ import annotations

import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / ".build" / "dist"
BUILD = ROOT / ".build" / "work"
APP = ROOT / "app"
DATA_NAME = ".weblauncher"
LEGACY_DATA_NAME = ".dshlauncher"
SAFE_DIRS = {DATA_NAME, LEGACY_DATA_NAME}
APP_NAME = "weblauncher.exe" if sys.platform == "win32" else "weblauncher"
ASSETS = ROOT / "packaging" / "assets"


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
            str(ROOT / "packaging" / "weblauncher.spec"),
        ],
        cwd=ROOT,
        check=True,
    )


def deploy() -> None:
    source = DIST / "weblauncher"
    if not source.is_dir():
        raise SystemExit(f"没有找到构建产物：{source}")
    APP.mkdir(parents=True, exist_ok=True)

    try:
        _sync(source)
        if ASSETS.is_dir():
            target_assets = APP / "assets"
            target_assets.mkdir(parents=True, exist_ok=True)
            for asset in ASSETS.iterdir():
                if asset.is_file():
                    shutil.copy2(asset, target_assets / asset.name)
    except (shutil.Error, OSError) as exc:
        raise SystemExit(
            "部署失败：目标文件写不进去，通常是被其它程序占用"
            "（应用窗口/服务还在运行，或编辑器、杀软正打开 app/_internal 里的文件）。"
            "关掉占用者后重试。\n"
            f"详细：{exc}"
        ) from exc

    print(f"已部署到 {APP}")
    exe = APP / APP_NAME
    if exe.exists():
        print(f"  {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")


def _sync(source: Path) -> None:
    # 只覆盖内容有变化的文件：_internal 里大多数文件每次构建都一样，跳过它们
    # 既省时间，也避免被别的程序映射着、改不动的文件挡住整次部署。
    for root, _, files in os.walk(source):
        relative = Path(root).relative_to(source)
        target_root = APP / relative
        target_root.mkdir(parents=True, exist_ok=True)
        for name in files:
            if relative == Path() and name in SAFE_DIRS:
                continue
            origin = Path(root) / name
            destination = target_root / name
            if _identical(origin, destination):
                continue
            shutil.copy2(origin, destination)

    # 清理上一版遗留、本次已不存在的文件（数据目录除外）
    for root, dirs, files in os.walk(APP, topdown=False):
        relative = Path(root).relative_to(APP)
        if relative.parts[:1] and relative.parts[0] in SAFE_DIRS:
            continue
        for name in files:
            if not (source / relative / name).exists():
                (Path(root) / name).unlink(missing_ok=True)
        for name in dirs:
            if relative == Path() and name in SAFE_DIRS:
                continue
            if not (source / relative / name).exists():
                shutil.rmtree(Path(root) / name, ignore_errors=True)


def _identical(origin: Path, destination: Path) -> bool:
    try:
        if origin.stat().st_size != destination.stat().st_size:
            return False
        return filecmp.cmp(origin, destination, shallow=False)
    except OSError:
        return False


if __name__ == "__main__":
    if "--skip-build" not in sys.argv:
        build()
    deploy()
