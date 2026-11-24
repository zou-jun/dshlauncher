"""端口监听者探测：一次扫描缓存全部监听端口，短 TTL 内复用。"""

from __future__ import annotations

import threading
import time

import psutil


class PortInspector:
    def __init__(self, ttl: float = 0.5) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._scanned_at = 0.0
        self._listeners: dict[int, int | None] = {}

    def reset(self) -> None:
        with self._lock:
            self._scanned_at = 0.0
            self._listeners = {}

    def _scan(self) -> dict[int, int | None]:
        now = time.monotonic()
        with self._lock:
            if now - self._scanned_at < self.ttl:
                return self._listeners
            listeners: dict[int, int | None] = {}
            try:
                connections = psutil.net_connections(kind="tcp")
            except (psutil.Error, OSError):
                return self._listeners
            for conn in connections:
                if not conn.laddr or conn.status != psutil.CONN_LISTEN:
                    continue
                port = int(conn.laddr.port)
                if port not in listeners or (listeners[port] is None and conn.pid is not None):
                    listeners[port] = conn.pid
            self._listeners = listeners
            self._scanned_at = now
            return listeners

    def owner_process(self, port: int) -> psutil.Process | None:
        pid = self._scan().get(port)
        if pid is None:
            return None
        try:
            return psutil.Process(pid)
        except psutil.Error:
            return None

    def owner(self, port: int) -> str | None:
        pid = self._scan().get(port)
        if pid is None:
            if port not in self._listeners:
                return None
            return f"未知进程（监听 {port}）"
        try:
            proc = psutil.Process(pid)
            return f"pid {pid} {proc.name()} :: {' '.join(proc.cmdline())[:200]}"
        except psutil.Error:
            return f"pid {pid}"


__all__ = ["PortInspector"]
