"""外部依赖发现：node、dsh 入口、Chromium 系浏览器。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0

#: 优先顺序：用的人最多、可复现性最好的排前面。
BROWSER_ORDER = ("chrome", "edge", "chromium", "brave")

#: dsh 包内的入口文件，相对 node_modules 根。
DSH_ENTRY = ("@deepseek-ai", "dsh", "lib", "bin.js")

_BROWSER_STEMS = {
    "chrome.exe": "chrome",
    "msedge.exe": "edge",
    "chromium.exe": "chromium",
    "brave.exe": "brave",
    "chrome": "chrome",
    "google-chrome": "chrome",
    "google-chrome-stable": "chrome",
    "chromium": "chromium",
    "chromium-browser": "chromium",
    "microsoft-edge": "edge",
    "microsoft-edge-stable": "edge",
    "brave-browser": "brave",
    "brave": "brave",
}


class DiscoveryError(RuntimeError):
    """缺少必需的外部依赖。"""


@dataclass(frozen=True)
class Browser:
    family: str
    path: Path
    version: str | None = None


def _env(name: str) -> str | None:
    value = os.environ.get("DSHLAUNCHER_" + name, "").strip()
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


def _versioned_dirs(pattern: str) -> list[Path]:
    """展开 ``~/<pattern>`` 并按名字倒序（新版优先）。"""
    try:
        return sorted((path for path in Path.home().glob(pattern) if path.is_dir()), reverse=True)
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


def node_exe(configured: Path | None = None) -> Path:
    candidate = _first_file([configured, _env("NODE"), *node_candidates()])
    if candidate is None:
        raise DiscoveryError("找不到 node：请安装 Node.js，或用 --node / DSHLAUNCHER_NODE 指定可执行文件")
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


def dsh_candidates() -> list[Path | str | None]:
    candidates: list[Path | str | None] = []
    shim = shutil.which("dsh")
    if shim is not None:
        candidates.extend(_shim_candidates(Path(shim)))
    for root in _node_module_roots():
        candidates.append(root.joinpath(*DSH_ENTRY))
    return candidates


def dsh_bin(configured: Path | None = None) -> Path:
    candidate = _first_file([configured, _env("DSH_BIN"), *dsh_candidates()])
    if candidate is not None:
        return candidate
    raise DiscoveryError(
        "找不到 @deepseek-ai/dsh 的 lib/bin.js：先执行 `npm i -g @deepseek-ai/dsh`，"
        "或用 --dsh-bin / DSHLAUNCHER_DSH_BIN 指定"
    )


# ── 浏览器 ────────────────────────────────────────────────────────────
def _windows_browser_candidates(family: str) -> list[Path]:
    layout: dict[str, list[tuple[str, tuple[str, ...]]]] = {
        "chrome": [
            ("ProgramFiles", ("Google", "Chrome", "Application", "chrome.exe")),
            ("ProgramFiles(x86)", ("Google", "Chrome", "Application", "chrome.exe")),
            ("LOCALAPPDATA", ("Google", "Chrome", "Application", "chrome.exe")),
        ],
        "edge": [
            ("ProgramFiles(x86)", ("Microsoft", "Edge", "Application", "msedge.exe")),
            ("ProgramFiles", ("Microsoft", "Edge", "Application", "msedge.exe")),
        ],
        "chromium": [("ProgramFiles", ("Chromium", "Application", "chrome.exe"))],
        "brave": [
            ("ProgramFiles", ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
            ("ProgramFiles(x86)", ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
        ],
    }
    candidates: list[Path] = []
    for env_name, parts in layout.get(family, []):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base).joinpath(*parts))
    return candidates


_POSIX_COMMANDS: dict[str, tuple[str, ...]] = {
    "chrome": ("google-chrome", "google-chrome-stable"),
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
    "chromium": ("chromium", "chromium-browser"),
    "brave": ("brave-browser", "brave"),
}

_MACOS_APPS: dict[str, str] = {
    "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "chromium": "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "brave": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
}


def _browser_candidates(family: str) -> list[Path | str | None]:
    if WINDOWS:
        return list(_windows_browser_candidates(family))
    if MACOS:
        return [Path(_MACOS_APPS[family])] + [shutil.which(name) for name in _POSIX_COMMANDS[family]]
    return [shutil.which(name) for name in _POSIX_COMMANDS[family]]


def _family_of(path: Path) -> str:
    stem = path.name.lower()
    if stem in _BROWSER_STEMS:
        return _BROWSER_STEMS[stem]
    return BROWSER_ORDER[0]


def browser_version(path: Path) -> str | None:
    if not WINDOWS:
        try:
            result = subprocess.run([str(path), "--version"], capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        text = (result.stdout or result.stderr).strip()
        return text.splitlines()[0] if text else None

    pattern = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
    for parent in (path.parent, path.parent.parent):
        try:
            versions = [
                entry.name for entry in parent.iterdir() if entry.is_dir() and pattern.match(entry.name)
            ]
        except OSError:
            continue
        if versions:
            return max(versions, key=lambda value: tuple(int(part) for part in value.split(".")))
    return None


def browser_exe(configured: str | None = None) -> Browser:
    """按 family 名或显式路径定位 Chromium 系浏览器。"""
    requested = configured or _env("BROWSER")
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.is_file():
            path = candidate
            family = _family_of(path)
            return Browser(family, path, browser_version(path))
        family = requested.strip().lower()
        if family not in BROWSER_ORDER:
            raise DiscoveryError(
                f"未知浏览器 {requested!r}：可选 {', '.join(BROWSER_ORDER)}，或直接给可执行文件路径"
            )
        path = _first_file(_browser_candidates(family))
        if path is None:
            raise DiscoveryError(f"找不到 {family} 的可执行文件")
        return Browser(family, path, browser_version(path))

    for family in BROWSER_ORDER:
        path = _first_file(_browser_candidates(family))
        if path is not None:
            return Browser(family, path, browser_version(path))

    raise DiscoveryError(
        "找不到 Chromium 系浏览器（Chrome / Edge / Chromium / Brave）：无扩展的应用窗口只支持这一类浏览器"
    )
