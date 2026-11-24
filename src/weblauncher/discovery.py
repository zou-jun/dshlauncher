"""Chromium 系浏览器发现（与具体托管服务无关）。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

#: 优先顺序：用的人最多、可复现性最好的排前面。
BROWSER_ORDER = ("chrome", "edge", "chromium", "brave")

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
    value = os.environ.get("WEBLAUNCHER_" + name, "").strip()
    return value or None


def _first_file(candidates: Iterable[Path | str | None]) -> Path | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file():
            return path
    return None


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


@lru_cache(maxsize=16)
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


def reset_cache() -> None:
    browser_exe.cache_clear()
