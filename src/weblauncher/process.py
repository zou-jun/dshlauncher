"""进程工具：分离启动、树杀、PID + create_time 校验。"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
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


class ServiceLock:
    """跨进程服务动作锁：一次只允许一个 start/stop/restart。

    锁文件放在 ``services/<id>/service.lock``；持有者用 pid + create_time 校验，
    进程崩溃后下一次操作会自动清理。
    """

    def __init__(self, path: Path, *, timeout: float, label: str) -> None:
        self.path = path
        self.timeout = timeout
        self.label = label
        self.pid = os.getpid()
        self.create_time = psutil.Process().create_time()
        self._held = False

    def _holder(self) -> tuple[int, float] | None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return int(data["pid"]), float(data["create_time"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _fresh(self) -> bool:
        try:
            return time.time() - self.path.stat().st_mtime < 5.0
        except OSError:
            return False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0),
                    0o600,
                )
            except FileExistsError:
                holder = self._holder()
                if holder is not None and alive(*holder):
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"另一个 {self.label} 操作正在进行，请稍后重试") from None
                    time.sleep(0.1)
                    continue
                if holder is None and self._fresh():
                    if time.monotonic() >= deadline:
                        raise RuntimeError(f"另一个 {self.label} 操作正在进行，请稍后重试") from None
                    time.sleep(0.1)
                    continue
                with contextlib.suppress(OSError):
                    self.path.unlink(missing_ok=True)
                continue
            try:
                os.write(
                    fd,
                    json.dumps({"pid": self.pid, "create_time": self.create_time}).encode(),
                )
            finally:
                os.close(fd)
            self._held = True
            return

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        holder = self._holder()
        if holder is not None and holder[0] == self.pid and abs(holder[1] - self.create_time) < 1.0:
            with contextlib.suppress(OSError):
                self.path.unlink(missing_ok=True)

    def __enter__(self) -> ServiceLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


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
