"""在独立 Chromium 配置里打开无扩展的应用窗口。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil

from . import discovery, geometry, paths, platform
from .geometry import Rect
from .settings import Settings

#: 等窗口出现的最长时间（首次启动浏览器较慢）。
WINDOW_TIMEOUT = 10.0
SETTLE_RETRY = 0.8


def _profile_pids(profile_dir: Path, names: set[str]) -> set[int]:
    """命令行里带本启动器专用 user-data-dir 的浏览器进程。"""
    needle = str(profile_dir)
    wanted = {name.lower() for name in names}
    pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        name = (proc.info.get("name") or "").lower()
        if name not in wanted:
            continue
        if needle in " ".join(proc.info.get("cmdline") or []):
            pids.add(proc.pid)
    return pids


def _wait_window(profile_dir: Path, names: set[str], timeout: float = WINDOW_TIMEOUT) -> int | None:
    backend = platform.load()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = backend.find_window(_profile_pids(profile_dir, names))
        if hwnd is not None:
            return hwnd
        time.sleep(0.2)
    return None


def _settle(hwnd: int, target: Rect | None) -> None:
    """窗口过小或跑出屏幕时纠正成默认比例；用户自己调好的尺寸不动。"""
    if target is None:
        return
    backend = platform.load()
    work = backend.work_area()
    if work is None:
        return
    rect = backend.window_rect(hwnd)
    if rect is None or not geometry.needs_fix(rect, work):
        return
    backend.apply_rect(hwnd, target)
    time.sleep(SETTLE_RETRY)
    rect = backend.window_rect(hwnd)
    if rect is not None and geometry.needs_fix(rect, work):
        backend.apply_rect(hwnd, target)


def ozone_args(settings: Settings) -> list[str]:
    """Linux 上显式选择 Chrome 的显示后端；auto 交给 Chrome 自己判断。"""
    if sys.platform.startswith("linux") and settings.ozone in {"x11", "wayland"}:
        return [f"--ozone-platform={settings.ozone}"]
    return []


def build_args(
    settings: Settings,
    browser: discovery.Browser,
    url: str,
    target: Rect | None,
    *,
    window_control: bool,
) -> list[str]:
    """Chrome 的应用窗口命令行。"""
    args = [
        str(browser.path),
        f"--app={url}",
        f"--user-data-dir={settings.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--no-service-autorun",
        "--disable-features=Translate",
    ]
    args += ozone_args(settings)
    if target is not None:
        args.append(f"--window-size={target.width},{target.height}")
        # 原生 Wayland 不允许客户端指定位置，传了也会被忽略。
        if window_control:
            args.append(f"--window-position={target.x},{target.y}")
    return args


def launch(settings: Settings, url: str) -> str:
    """打开应用窗口；已有窗口时只置前。返回 ``new`` 或 ``focused``。

    原生 Wayland（``ozone=auto`` / ``wayland``）没有可用的窗口控制 API，
    dedupe 与尺寸纠正在该模式下不生效，只能每次都新开窗口。
    """
    backend = platform.load()
    browser = discovery.browser_exe(settings.browser)
    names = backend.process_names(browser.family)
    profile = settings.profile_dir
    window_control = backend.supports_window_control(settings.ozone)

    work = backend.work_area()
    target = geometry.preferred_rect(work, **settings.window_kwargs()) if work is not None else None

    if settings.dedupe and window_control:
        existing = backend.find_window(_profile_pids(profile, names))
        if existing is not None:
            _settle(existing, target)
            backend.present(existing)
            return "focused"

    profile.mkdir(parents=True, exist_ok=True)
    args = build_args(settings, browser, url, target, window_control=window_control)
    subprocess.Popen(
        args,
        cwd=str(browser.path.parent),
        env=paths.child_env(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **backend.detach_kwargs(),
    )

    if window_control:
        hwnd = _wait_window(profile, names)
        if hwnd is not None:
            _settle(hwnd, target)
    return "new"
