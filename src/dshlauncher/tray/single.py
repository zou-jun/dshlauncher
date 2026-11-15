"""托盘单实例锁：pid + create_time，避免 PID 复用。"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from ..paths import Paths

LOCK_NAME = "tray.lock"


@dataclass(frozen=True)
class Lock:
    path: Path
    pid: int
    create_time: float


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def alive(pid: int, create_time: float) -> bool:
    """pid 存在且启动时间一致（防 PID 复用）。"""
    try:
        proc = psutil.Process(pid)
        return abs(proc.create_time() - create_time) < 1.0
    except (psutil.Error, OSError):
        return False


def _holder(path: Path) -> tuple[int, float] | None:
    data = read_json(path)
    if data is None:
        return None
    try:
        return int(data["pid"]), float(data["create_time"])
    except (KeyError, TypeError, ValueError):
        return None


def _fresh(path: Path, seconds: float = 5.0) -> bool:
    """锁文件刚创建、内容还没写完：保守地当作有人在抢。"""
    try:
        return time.time() - path.stat().st_mtime < seconds
    except OSError:
        return False


def acquire_lock(paths: Paths) -> Lock | None:
    """抢到返回 Lock；已有活着的托盘（或正在写锁）返回 None。"""
    paths.ensure()
    path = paths.tray_lock
    for _ in range(5):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            holder = _holder(path)
            if holder is not None and alive(*holder):
                return None
            if holder is None and _fresh(path):
                return None
            path.unlink(missing_ok=True)
            continue
        try:
            pid = os.getpid()
            create_time = psutil.Process().create_time()
            os.write(fd, json.dumps({"pid": pid, "create_time": create_time}).encode())
        finally:
            os.close(fd)
        return Lock(path, pid, create_time)
    return None


def release_lock(lock: Lock) -> None:
    with contextlib.suppress(OSError):
        holder = _holder(lock.path)
        if holder is not None and holder[0] == lock.pid:
            lock.path.unlink(missing_ok=True)
