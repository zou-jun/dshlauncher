"""进程工具：分离启动、树杀、PID + create_time 校验。"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from typing import Any

import psutil


def kill_tree(pid: int) -> None:
    """先礼后兵地终止整棵进程树（应用内核/子进程都会一起走）。"""
    try:
        proc = psutil.Process(pid)
    except psutil.Error:
        return
    targets: list[psutil.Process] = []
    with contextlib.suppress(psutil.Error):
        targets = proc.children(recursive=True)
    targets.append(proc)
    for target in targets:
        with contextlib.suppress(psutil.Error):
            target.terminate()
    _, alive = psutil.wait_procs(targets, timeout=5)
    for target in alive:
        with contextlib.suppress(psutil.Error):
            target.kill()
    if alive:
        psutil.wait_procs(alive, timeout=3)


def alive(pid: int, create_time: float) -> bool:
    """pid 存在且启动时间一致，防 PID 复用。"""
    try:
        proc = psutil.Process(pid)
        return abs(proc.create_time() - create_time) < 1.0
    except (psutil.Error, OSError):
        return False


def spawn(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log: Any,
    backend: Any,
) -> subprocess.Popen[Any]:
    """分离启动；当前 job 禁止 breakaway 时退回普通分离。"""
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
        "env": env,
    }
    try:
        return subprocess.Popen(argv, **kwargs, **backend.detach_kwargs(breakaway=True))
    except OSError:
        return subprocess.Popen(argv, **kwargs, **backend.detach_kwargs(breakaway=False))
