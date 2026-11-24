"""端口可用性：区分空闲、被占用、被系统保留（Windows 排除段）。

``connect()`` 探活发现不了「端口上没有进程，但内核禁止 bind」的情况：Windows
的 Hyper-V / WinNAT 会把一段端口登记为排除范围，在那里 bind 返回
WSAEACCES(10013)。这里用一次真实 bind 判定，并把命中的排除段翻译成人话。
"""

from __future__ import annotations

import errno
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache

#: 默认端口不可用时的回退序列。3080 是历史默认（浏览器 cookie 绑 host:port，
#: 换端口等于重新授权一次），其后取远离常见动态预留的高位端口。
FALLBACK_PORTS = (18080, 18081, 18082, 18083)

FREE = "free"
IN_USE = "in_use"
RESERVED = "reserved"
ERROR = "error"

_RANGE_LINE = re.compile(r"^(\d+)\s+(\d+)\s*\*?$")
_WSAEACCES = 10013
_WSAEADDRINUSE = 10048
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class Verdict:
    """一次 bind 探测的结果。"""

    status: str
    detail: str = ""

    @property
    def free(self) -> bool:
        return self.status == FREE

    @property
    def in_use(self) -> bool:
        return self.status == IN_USE

    @property
    def reserved(self) -> bool:
        return self.status == RESERVED

    def describe(self) -> str:
        if self.free:
            return "可用"
        if self.in_use:
            return "被占用"
        if self.reserved:
            return f"系统保留（{self.detail}）" if self.detail else "系统保留"
        return f"不可用（{self.detail}）" if self.detail else "不可用"


def _bind(host: str, port: int) -> None:
    """在 host:port 上试 bind；失败抛 OSError（测试替换点）。"""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.bind((host, port))


def _is_reserved(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == _WSAEACCES or exc.errno in {errno.EACCES, errno.EPERM}


def _is_in_use(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == _WSAEADDRINUSE or exc.errno in {
        errno.EADDRINUSE,
        _WSAEADDRINUSE,
    }


@lru_cache(maxsize=1)
def excluded_ranges() -> tuple[tuple[int, int], ...]:
    """Windows 的 TCP 排除端口段；其它平台或读取失败时为空。"""
    if sys.platform != "win32":
        return ()
    try:
        # netsh 是控制台程序；GUI 启动器里不加这个标志会闪一个终端窗口。
        flags = {"creationflags": CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        completed = subprocess.run(
            ["netsh", "interface", "ipv4", "show", "excludedportrange", "protocol=tcp"],
            capture_output=True,
            timeout=10,
            check=False,
            **flags,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    # 中文 Windows 的 netsh 输出是 GBK；只需要数字，按 UTF-8 宽松解码足够。
    text = completed.stdout.decode("utf-8", "replace")
    ranges: list[tuple[int, int]] = []
    for line in text.splitlines():
        match = _RANGE_LINE.match(line.strip())
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if 0 < start <= end <= 65535:
                ranges.append((start, end))
    return tuple(ranges)


def range_for(port: int) -> tuple[int, int] | None:
    """port 命中的排除段（start, end）；未命中返回 None。"""
    for start, end in excluded_ranges():
        if start <= port <= end:
            return (start, end)
    return None


def probe(host: str, port: int) -> Verdict:
    """真实 bind 一次判定端口状态。port=0 交给系统分配，按"可用"处理。"""
    if port == 0:
        return Verdict(FREE)
    try:
        _bind(host, port)
    except PermissionError as exc:
        return Verdict(RESERVED, _reserved_detail(port, exc))
    except OSError as exc:
        if _is_reserved(exc):
            return Verdict(RESERVED, _reserved_detail(port, exc))
        if _is_in_use(exc):
            return Verdict(IN_USE, str(exc))
        return Verdict(ERROR, str(exc))
    return Verdict(FREE)


def _reserved_detail(port: int, exc: OSError) -> str:
    hit = range_for(port)
    if hit:
        return f"{hit[0]}-{hit[1]}"
    return f"{exc}"


def reserved_message(host: str, port: int, verdict: Verdict | None = None) -> str:
    """EACCES 的可执行解释：命中区间 + 下一步。"""
    detail = (verdict or probe(host, port)).detail
    hit = range_for(port)
    if hit:
        span = f"{hit[0]}-{hit[1]}"
    elif detail and "-" in detail and detail.replace("-", "").isdigit():
        span = detail
    else:
        span = ""
    where = f"{host}:{port}"
    if span:
        head = f"端口 {where} 在 Windows 保留段 {span} 内，内核拒绝 bind（EACCES）"
    else:
        head = f"端口 {where} 被系统拒绝 bind（EACCES）"
    return (
        f"{head}。\n"
        f"换一个端口重试，例如 --port {FALLBACK_PORTS[0]}；"
        "查看全部保留段：netsh interface ipv4 show excludedportrange protocol=tcp"
    )


def candidates(
    preferred: int | None,
    requested: int,
    fallback: tuple[int, ...] = FALLBACK_PORTS,
) -> tuple[int, ...]:
    """待试端口：上次用过的 → 本次配置值 → 回退序列，去重且保持顺序。"""
    ordered = [port for port in (preferred, requested) if port is not None]
    ordered.extend(fallback)
    seen: set[int] = set()
    result: list[int] = []
    for port in ordered:
        if port not in seen:
            seen.add(port)
            result.append(port)
    return tuple(result)
