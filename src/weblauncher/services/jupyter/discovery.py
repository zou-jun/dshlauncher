"""定位 uv tool 安装的 Jupyter Lab，并推导同一环境里的 jupyter / python。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ...discovery import DiscoveryError

WINDOWS = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0


@dataclass(frozen=True)
class Install:
    argv: tuple[str, ...]
    env: Path | None
    jupyter: Path | None
    python: Path | None
    version: str | None = None

    @property
    def lab(self) -> Path | None:
        return Path(self.argv[0]) if self.argv and Path(self.argv[0]).is_file() else None


def _env(name: str) -> str | None:
    value = os.environ.get("WEBLAUNCHER_JUPYTER_" + name, "").strip()
    return value or None


def _run(args: list[str]) -> str | None:
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
    return result.stdout.strip() if result.returncode == 0 else None


def uv_tool_root() -> Path:
    configured = os.environ.get("UV_TOOL_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if WINDOWS:
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "uv" / "tools"
    return Path.home() / ".local" / "share" / "uv" / "tools"


def _env_from_lab(lab: Path) -> Path | None:
    """``<env>/Scripts/jupyter-lab.exe`` / ``<env>/bin/jupyter-lab`` → env。"""
    try:
        parent = lab.parent
    except OSError:
        return None
    candidate = parent.parent
    if (candidate / "pyvenv.cfg").is_file():
        return candidate
    return None


def _tools() -> list[Path]:
    root = uv_tool_root()
    try:
        return sorted((path for path in root.iterdir() if path.is_dir()), reverse=True)
    except OSError:
        return []


def _from_receipts() -> list[Path]:
    found: list[Path] = []
    for tool in _tools():
        receipt = tool / "uv-receipt.toml"
        try:
            data = tomllib.loads(receipt.read_text("utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        entries = data.get("tool", {}).get("entrypoints", [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("name") == "jupyter-lab":
                native = tool / ("Scripts/jupyter-lab.exe" if WINDOWS else "bin/jupyter-lab")
                path = native if native.is_file() else Path(str(entry.get("install-path") or "")).expanduser()
                if path.is_file():
                    found.append(path)
    return found


def _direct_globs() -> list[Path]:
    names = ("Scripts/jupyter-lab.exe", "bin/jupyter-lab") if WINDOWS else ("bin/jupyter-lab",)
    found: list[Path] = []
    for tool in _tools():
        for name in names:
            path = tool / name
            if path.is_file():
                found.append(path)
    return found


def _candidates(configured: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if configured is not None:
        candidates.append(configured)
    explicit = _env("JUPYTER_BIN")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(_from_receipts())
    candidates.extend(_direct_globs())
    which = shutil.which("jupyter-lab")
    if which:
        candidates.append(Path(which))
    candidates.append(Path.home() / ".local" / "bin" / ("jupyter-lab.exe" if WINDOWS else "jupyter-lab"))
    return candidates


def _derive(path: Path, env: Path | None) -> Install:
    if env is None:
        env = _env_from_lab(path)
    jupyter = None
    python = None
    if env is not None:
        jupyter = env / ("Scripts/jupyter.exe" if WINDOWS else "bin/jupyter")
        python = env / ("Scripts/python.exe" if WINDOWS else "bin/python")
        if not jupyter.is_file():
            jupyter = None
        if not python.is_file():
            python = None
    version = _run([str(path), "--version"])
    return Install((str(path),), env, jupyter, python, version)


@lru_cache(maxsize=8)
def find(configured: Path | None = None) -> Install:
    """显式配置 → PATH → uv-receipt → uv tool 目录 → ~/.local/bin。"""
    for candidate in _candidates(configured):
        if candidate.is_file():
            install = _derive(candidate, _env_from_lab(candidate))
            if install.lab is not None:
                return install
    raise DiscoveryError(
        "找不到 jupyter-lab：先执行 `uv tool install jupyterlab`，"
        "或用 --jupyter-bin / WEBLAUNCHER_JUPYTER_BIN 指定 jupyter-lab 可执行文件"
    )


def reset_cache() -> None:
    find.cache_clear()
