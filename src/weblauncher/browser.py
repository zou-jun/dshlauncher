"""在独立 Chromium 配置里打开无扩展的应用窗口。"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil

from . import discovery, geometry, paths, platform
from .geometry import Rect

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


def _wait_window(
    profile_dir: Path,
    names: set[str],
    *,
    backend: Any,
    timeout: float = WINDOW_TIMEOUT,
) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hwnd = backend.find_window(_profile_pids(profile_dir, names))
        if hwnd is not None:
            return hwnd
        time.sleep(0.2)
    return None


def _settle(hwnd: int, target: Rect | None, *, backend: Any) -> None:
    """窗口过小或跑出屏幕时纠正成默认比例；用户自己调好的尺寸不动。"""
    if target is None:
        return
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


def ozone_args(settings: Any) -> list[str]:
    """Linux 上显式选择 Chrome 的显示后端；auto 交给 Chrome 自己判断。"""
    if sys.platform.startswith("linux") and settings.ozone in {"x11", "wayland"}:
        return [f"--ozone-platform={settings.ozone}"]
    return []


def _base_args(settings: Any, browser: discovery.Browser) -> list[str]:
    return [
        str(browser.path),
        f"--user-data-dir={settings.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--no-service-autorun",
        "--disable-features=Translate",
    ]


def build_args(
    settings: Any,
    browser: discovery.Browser,
    url: str,
    target: Rect | None,
    *,
    window_control: bool,
) -> list[str]:
    """Chrome 的独立应用窗口命令行（``--app``）。"""
    args = [str(browser.path), f"--app={url}", *_base_args(settings, browser)[1:]]
    args += ozone_args(settings)
    if target is not None:
        args.append(f"--window-size={target.width},{target.height}")
        # 原生 Wayland 不允许客户端指定位置，传了也会被忽略。
        if window_control:
            args.append(f"--window-position={target.x},{target.y}")
    return args


def build_tab_args(
    settings: Any,
    browser: discovery.Browser,
    url: str,
    target: Rect | None,
    *,
    window_control: bool,
    new_window: bool,
) -> list[str]:
    """普通浏览器窗口的标签页命令行。

    第一次用 ``--new-window`` 建窗口；之后只给 URL，Chromium 会在同一个
    profile 的现有窗口里追加标签页。
    """
    args = _base_args(settings, browser)
    args += ozone_args(settings)
    if new_window:
        args.append("--new-window")
        if target is not None:
            args.append(f"--window-size={target.width},{target.height}")
            if window_control:
                args.append(f"--window-position={target.x},{target.y}")
    args.append(url)
    return args


def _popen(args: list[str], *, backend: Any) -> None:
    kwargs = {
        "cwd": str(Path(args[0]).parent),
        "env": paths.child_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    try:
        subprocess.Popen(args, **kwargs, **backend.detach_kwargs())
    except OSError:
        # 当前 job 不允许 breakaway（例如从受限任务启动托盘）时退回普通分离。
        subprocess.Popen(args, **kwargs, **backend.detach_kwargs(breakaway=False))


def _launch_tabbed(
    settings: Any,
    browser: discovery.Browser,
    url: str,
    *,
    backend: Any,
    names: set[str],
    profile: Path,
    window_control: bool,
    target: Rect | None,
) -> str:
    profile.mkdir(parents=True, exist_ok=True)
    existing = _profile_pids(profile, names)
    new_window = not existing
    args = build_tab_args(
        settings,
        browser,
        url,
        target,
        window_control=window_control,
        new_window=new_window,
    )
    _popen(args, backend=backend)
    if new_window and window_control:
        hwnd = _wait_window(profile, names, backend=backend)
        if hwnd is not None:
            _settle(hwnd, target, backend=backend)
    return "new" if new_window else "tab"


def launch(
    settings: Any,
    url: str,
    *,
    backend: Any | None = None,
    dedupe: bool | None = None,
) -> str:
    """打开 UI；默认返回 ``new`` / ``focused``，单窗口模式返回 ``new`` / ``tab``。

    ``dedupe=False`` 强制新开。原生 Wayland（``ozone=auto`` /
    ``wayland``）没有可用的窗口控制 API，dedupe 与尺寸纠正在该模式下不生效，
    只能每次都新开窗口。
    """
    backend = backend or platform.load()
    assert backend is not None
    browser = discovery.browser_exe(settings.browser)
    names = backend.process_names(browser.family)
    profile = settings.profile_dir
    window_control = backend.supports_window_control(settings.ozone)

    work = backend.work_area()
    target = geometry.preferred_rect(work, **settings.window_kwargs()) if work is not None else None

    if bool(getattr(settings, "single_window", False)):
        return _launch_tabbed(
            settings,
            browser,
            url,
            backend=backend,
            names=names,
            profile=profile,
            window_control=window_control,
            target=target,
        )

    use_dedupe = settings.dedupe if dedupe is None else dedupe
    if use_dedupe and window_control:
        existing = backend.find_window(_profile_pids(profile, names))
        if existing is not None:
            _settle(existing, target, backend=backend)
            backend.present(existing)
            return "focused"

    profile.mkdir(parents=True, exist_ok=True)
    args = build_args(settings, browser, url, target, window_control=window_control)
    _popen(args, backend=backend)

    if window_control:
        hwnd = _wait_window(profile, names, backend=backend)
        if hwnd is not None:
            _settle(hwnd, target, backend=backend)
    return "new"
