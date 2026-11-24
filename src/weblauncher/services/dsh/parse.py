"""dsh 输出解析：token URL、进程归属与启动失败原因。"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from ...logs import START_MARKER

BIN_JS_MARKER = "@deepseek-ai/dsh/lib/bin.js"
#: 外部手动启动的 dsh 可能是 PATH 上的 shim（符号链接/脚本），不一定带 bin.js 路径。
DSH_NAMES = {"dsh", "dsh.cmd", "dsh.exe", "dsh.js"}
URL_PATTERN = re.compile(r"dsh web: (https?://\S+)")


def is_dsh_cmdline(cmdline: str) -> bool:
    """判断命令行是不是 `dsh web`（兼容 bin.js 路径和 PATH 上的 shim）。

    只认 "dsh 可执行文件 + 紧邻的 web 子命令"，避免把 ``node dsh web.js``
    这类无关进程（Windows 上 `stop` 会清理它们）当成服务。
    """
    joined = cmdline.replace("\\", "/")
    if " web" not in joined:
        return False
    if BIN_JS_MARKER in joined:
        return True
    parts = [part.strip('"') for part in joined.split()]
    return any(
        Path(part).name in DSH_NAMES and parts[index + 1] == "web" for index, part in enumerate(parts[:-1])
    )


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
