"""服务日志的尾部读取、启动标记解析与轮转。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

#: 每次启动写入日志的标记行；只有它之后的 URL 属于当前进程（token 每进程都变）。
START_MARKER = "[launcher] start"
URL_PATTERN = re.compile(r"dsh web: (https?://\S+)")

LOG_ROTATE_BYTES = 5 * 1024 * 1024
TAIL_BYTES = 256 * 1024
TOKEN_RE = re.compile(r"(?i)([?&](?:token|access_token)=)[^&\s]+")
ASSIGN_RE = re.compile(r"(?i)(\b(?:token|password|secret)\s*=\s*)(\"[^\"]*\"|'[^']*'|[^\s]+)")


def redact(text: str) -> str:
    """审计/状态弹窗里去掉 URL 查询和配置赋值中的 token。"""
    text = ASSIGN_RE.sub(lambda match: match.group(1) + '"<redacted>"', text)
    return TOKEN_RE.sub(r"\1<redacted>", text)


def parse_url(text: str) -> str | None:
    """取最后一个启动标记之后的 token URL（标记之前的是上一个进程的）。"""
    marker = text.rfind(START_MARKER)
    if marker != -1:
        text = text[marker:]
    matches = URL_PATTERN.findall(text)
    return matches[-1] if matches else None


def url_port(url: str) -> int | None:
    """URL 里的端口；解析失败返回 None。"""
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def startup_failure(text: str, lines: int = 12) -> str:
    """捞出本次启动的失败原因，而不是把日志尾部整块丢给用户。

    dsh 失败时会先打印 ``dsh: startup failed`` 块（真正的 EOF 原因），随后才是
    「插件在等某个服务」的长表；只 tail 最后几行必然只剩后者。
    """
    marker = text.rfind(START_MARKER)
    if marker != -1:
        text = text[marker:]
    rows = text.splitlines()
    for index, row in enumerate(rows):
        if "startup failed" in row:
            block: list[str] = []
            for line in rows[index:]:
                stripped = line.strip()
                # 失败块之后是「插件在等某个服务」的长表和诊断路径，都不是原因。
                if stripped.startswith(("Plugins waiting", "Full diagnostics")):
                    break
                if stripped.startswith("at "):
                    continue
                if not stripped and block and not block[-1].strip():
                    continue
                block.append(line)
                if len(block) >= lines:
                    break
            return "\n".join(block).strip()
    return "\n".join(rows[-lines:]).strip()


def tail_text(path: Path) -> str:
    """日志尾部（最多 ``TAIL_BYTES``），覆盖最近一次启动。"""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            return handle.read().decode("utf-8", "replace")
    except OSError:
        return ""


def rotate(path: Path, limit: int = LOG_ROTATE_BYTES) -> None:
    """超过 ``limit`` 时把日志挪到 ``<name>.1``，失败交给下一次启动。"""
    try:
        if path.exists() and path.stat().st_size > limit:
            rotated = path.with_name(path.name + ".1")
            rotated.unlink(missing_ok=True)
            path.replace(rotated)
    except OSError:
        pass
