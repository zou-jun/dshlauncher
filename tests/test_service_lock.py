"""跨进程服务动作锁：互斥、超时与陈旧锁清理。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weblauncher.process import ServiceLock


def test_lock_is_exclusive_and_reusable(tmp_path: Path) -> None:
    path = tmp_path / "service.lock"
    first = ServiceLock(path, timeout=1.0, label="demo")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="另一个 demo 操作正在进行"):
            ServiceLock(path, timeout=0.1, label="demo").acquire()
    finally:
        first.release()
    second = ServiceLock(path, timeout=1.0, label="demo")
    second.acquire()
    second.release()
    assert not path.exists()


def test_stale_lock_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "service.lock"
    path.write_text(json.dumps({"pid": 999999, "create_time": 0}), "utf-8")
    lock = ServiceLock(path, timeout=1.0, label="demo")
    lock.acquire()
    try:
        assert json.loads(path.read_text("utf-8"))["pid"] == lock.pid
    finally:
        lock.release()
