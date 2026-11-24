"""dsh 运行时发现：node 与 ``@deepseek-ai/dsh/lib/bin.js``。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from ...discovery import DiscoveryError

WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0

#: dsh 包内的入口文件，相对 node_modules 根。
DSH_ENTRY = ("@deepseek-ai", "dsh", "lib", "bin.js")


def _env(name: str) -> str | None:
    value = os.environ.get("WEBLAUNCHER_DSH_" + name, "").strip()
    return value or None


def _first_file(candidates: Iterable[Path | str | None]) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _run_command(args: list[str]) -> str | None:
    """跑一个探测用的命令；失败或超时都当作没有输出。"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _version_key(path: Path) -> tuple[int, ...]:
    parts = re.findall(r"\d+", path.name)
    return tuple(int(part) for part in parts) or (0,)


def _versioned_dirs(pattern: str) -> list[Path]:
    """展开 ``~/<pattern>`` 并按版本号倒序（新版优先）。"""
    try:
        return sorted(
            (path for path in Path.home().glob(pattern) if path.is_dir()),
            key=_version_key,
            reverse=True,
        )
    except OSError:
        return []


# ── node ──────────────────────────────────────────────────────────────
def node_candidates() -> list[Path | str | None]:
    """node 可执行文件的候选，按优先级排列。

    GUI（.desktop）启动时没有 shell 的 PATH，所以 nvm / fnm / volta 这些
    常见版本管理器目录要显式探测。
    """
    candidates: list[Path | str | None] = [shutil.which("node")]
    if WINDOWS:
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(Path(base) / "nodejs" / "node.exe")
        return candidates

    candidates.append(Path("/usr/local/bin/node"))
    candidates.append(Path("/usr/bin/node"))
    candidates.append(Path("/opt/homebrew/bin/node"))
    candidates.append(Path.home() / ".local" / "bin" / "node")
    for root in _versioned_dirs(".nvm/versions/node/*"):
        candidates.append(root / "bin" / "node")
    for root in _versioned_dirs(".local/share/fnm/node-versions/*"):
        candidates.append(root / "installation" / "bin" / "node")
    candidates.append(Path.home() / ".volta" / "bin" / "node")
    candidates.append(Path.home() / ".asdf" / "shims" / "node")
    return candidates


@lru_cache(maxsize=16)
def node_exe(configured: Path | None = None) -> Path:
    candidate = _first_file([configured, _env("NODE"), *node_candidates()])
    if candidate is None:
        raise DiscoveryError("找不到 node：请安装 Node.js，或用 --node / WEBLAUNCHER_DSH_NODE 指定可执行文件")
    return candidate


# ── dsh ───────────────────────────────────────────────────────────────
def _node_module_roots() -> list[Path]:
    """全局 node_modules 根目录：包管理器查询 + 常见固定位置。"""
    roots: list[Path] = []
    for manager, args in (("npm", ["root", "-g"]), ("pnpm", ["root", "-g"])):
        exe = shutil.which(manager)
        if exe is None:
            continue
        output = _run_command([exe, *args])
        for line in reversed((output or "").splitlines()):
            line = line.strip()
            if line:
                roots.append(Path(line))
                break

    npm = shutil.which("npm")
    if npm is not None:
        prefix = (_run_command([npm, "config", "get", "prefix"]) or "").strip()
        if prefix:
            roots.append(Path(prefix) / "node_modules" if WINDOWS else Path(prefix) / "lib" / "node_modules")

    if WINDOWS:
        for env_name in ("APPDATA", "LOCALAPPDATA"):
            base = os.environ.get(env_name)
            if base:
                roots.append(Path(base) / "npm" / "node_modules")
    else:
        roots.extend(
            [
                Path.home() / ".local" / "lib" / "node_modules",
                Path.home() / ".local" / "share" / "pnpm" / "global" / "5" / "node_modules",
                Path.home() / ".npm-global" / "lib" / "node_modules",
                Path("/usr/local/lib/node_modules"),
                Path("/usr/lib/node_modules"),
                Path("/opt/homebrew/lib/node_modules"),
            ]
        )
    return roots


def _shim_candidates(shim: Path) -> list[Path]:
    """从 PATH 上的 dsh shim 推导 bin.js。

    Linux 上 `npm i -g` 常见两种布局：
    - ``~/.local/bin/dsh`` 直接指向 ``.../@deepseek-ai/dsh/lib/bin.js``
    - ``/usr/local/bin/dsh`` 是普通脚本，真实入口在 ``/usr/local/lib/node_modules``
    """
    candidates: list[Path] = []
    try:
        resolved = shim.resolve()
    except OSError:
        resolved = shim
    if resolved.name == "bin.js" and "@deepseek-ai" in resolved.parts:
        candidates.append(resolved)
    for base in (shim.parent, resolved.parent):
        candidates.append(base / "node_modules" / Path(*DSH_ENTRY))
        candidates.append(base.parent / "lib" / "node_modules" / Path(*DSH_ENTRY))
    return candidates


@lru_cache(maxsize=16)
def dsh_bin(configured: Path | None = None) -> Path:
    """按代价从低到高查找 bin.js：显式配置 → PATH shim → 包管理器查询。

    包管理器查询要起 ``npm``/``pnpm`` 子进程（Windows 上约 1 秒），
    所以必须等前面的候选都落空再执行。
    """
    candidate = _first_file([configured, _env("BIN")])
    if candidate is not None:
        return candidate

    shim = shutil.which("dsh")
    if shim is not None:
        candidate = _first_file(_shim_candidates(Path(shim)))
        if candidate is not None:
            return candidate

    for root in _node_module_roots():
        entry = root.joinpath(*DSH_ENTRY)
        if entry.is_file():
            return entry

    raise DiscoveryError(
        "找不到 @deepseek-ai/dsh 的 lib/bin.js：先执行 `npm i -g @deepseek-ai/dsh`，"
        "或用 --dsh-bin / WEBLAUNCHER_DSH_BIN 指定"
    )


def reset_cache() -> None:
    """清空进程级发现缓存（测试或安装完依赖后重新探测）。"""
    node_exe.cache_clear()
    dsh_bin.cache_clear()
