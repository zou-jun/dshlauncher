"""托盘 loopback IPC：信息文件、客户端与只接受 token 的本地服务器。"""

from __future__ import annotations

import contextlib
import hmac
import json
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from .. import paths
from ..paths import Paths
from .single import alive, read_json

INFO_NAME = "tray.json"
START_WAIT = 30.0
CONNECT_TIMEOUT = 5.0


class TrayUnavailable(RuntimeError):
    """没有可用的托盘进程（未启动、已退出或信息文件损坏）。"""


def _read_info(paths_: Paths) -> dict[str, Any] | None:
    data = read_json(paths_.tray_info)
    if data is None:
        return None
    try:
        if int(data["port"]) <= 0 or not str(data["token"]):
            return None
        int(data["pid"])
        float(data["create_time"])
    except (KeyError, TypeError, ValueError):
        return None
    return data


def running(paths_: Paths) -> tuple[int, int] | None:
    """正在运行的托盘 ``(pid, IPC 端口)``；没有或信息已过期返回 ``None``。"""
    info = _read_info(paths_)
    if info is None:
        return None
    try:
        pid = int(info["pid"])
        if not alive(pid, float(info["create_time"])):
            return None
        return pid, int(info["port"])
    except (KeyError, TypeError, ValueError):
        return None


def _write_info(paths_: Paths, data: dict[str, Any]) -> None:
    paths.write_atomic(paths_.tray_info, json.dumps(data))


def _clear_info(paths_: Paths) -> None:
    with contextlib.suppress(OSError):
        paths_.tray_info.unlink(missing_ok=True)


def _request(info: dict[str, Any], command: str, timeout: float) -> str:
    payload = json.dumps({"token": info["token"], "command": command}).encode() + b"\n"
    with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=CONNECT_TIMEOUT) as conn:
        conn.settimeout(timeout)
        conn.sendall(payload)
        line = conn.makefile("rb").readline(65536)
    reply = json.loads(line or b"{}")
    if not isinstance(reply, dict) or not reply.get("ok"):
        error = reply.get("error") if isinstance(reply, dict) else None
        raise RuntimeError(str(error or "托盘拒绝请求"))
    return str(reply.get("result") or "")


def _send(paths_: Paths, command: str, timeout: float, *, wait: float = 0.0) -> str:
    deadline = time.monotonic() + wait
    while True:
        info = _read_info(paths_)
        if info is not None and alive(int(info["pid"]), float(info["create_time"])):
            try:
                return _request(info, command, timeout)
            except (OSError, ValueError):
                pass  # Agent 正在启动/退出，短暂重试
        if time.monotonic() >= deadline:
            raise TrayUnavailable("没有运行中的控制台")
        time.sleep(0.2)


def send_open(paths_: Paths, timeout: float, *, wait: float = 0.0) -> str:
    """让常驻 Agent 打开服务窗口；``wait`` 内反复重试等待就绪。"""
    return _send(paths_, "open", timeout, wait=wait)


def send_ui(paths_: Paths, timeout: float, *, wait: float = 0.0, target: str = "/#/") -> str:
    """请求一个一次性控制台入口 URL。"""
    return _send(paths_, f"ui {target}".strip(), timeout, wait=wait)


class IpcServer:
    """只接受 loopback + 随机 token 的「打开窗口」请求。"""

    def __init__(self, handler: Callable[[str], str], token: str) -> None:
        self._handler = handler
        self._token = token
        self._closed = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = int(self._sock.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="dsh-tray-ipc", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        with contextlib.suppress(OSError):
            self._sock.close()

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), name="dsh-tray-ipc-conn", daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            try:
                conn.settimeout(CONNECT_TIMEOUT)
                request = json.loads(conn.makefile("rb").readline(8192) or b"{}")
            except (OSError, ValueError):
                return
            if not isinstance(request, dict):
                return

            if not hmac.compare_digest(str(request.get("token", "")).encode(), self._token.encode()):
                reply: dict[str, Any] = {"ok": False, "error": "unauthorized"}
            else:
                try:
                    reply = {"ok": True, "result": self._handler(str(request.get("command", "")))}
                except Exception as exc:  # noqa: BLE001 - 把失败原因回传给发起方
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            with contextlib.suppress(OSError):
                conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode())
