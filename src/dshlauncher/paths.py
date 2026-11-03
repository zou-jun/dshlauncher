"""运行时数据目录与文件位置。

数据默认放在可执行文件同级的 `.dshlauncher/`；源码运行时即项目根目录下的
`.dshlauncher/`。目标位置不可写（例如 exe 装在 Program Files）时回退到当前
用户的数据目录，可用 `DSHLAUNCHER_HOME` 强制指定。
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

DATA_DIR_NAME = ".dshlauncher"


def _source_root() -> Path:
    """源码运行时定位项目根：向上找带 pyproject.toml 的目录。"""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def executable_dir() -> Path:
    """可执行文件所在目录；源码运行时是项目根目录（src 布局不影响定位）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _source_root()


def _user_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "dshlauncher"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dshlauncher"
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "dshlauncher"
    return Path.home() / ".local" / "state" / "dshlauncher"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", "utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def data_dir() -> Path:
    override = os.environ.get("DSHLAUNCHER_HOME")
    if override:
        path = Path(override).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
    beside_exe = executable_dir() / DATA_DIR_NAME
    if _writable(beside_exe):
        return beside_exe
    fallback = _user_data_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def ensure_data_dir() -> Path:
    path = data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path() -> Path:
    return data_dir() / "state.json"


def log_path() -> Path:
    return data_dir() / "dsh-web.log"


def launcher_log_path() -> Path:
    return data_dir() / "launcher.log"


def profile_dir() -> Path:
    return data_dir() / "browser"


def config_path() -> Path:
    return data_dir() / "config.toml"


def child_env() -> dict[str, str]:
    """给子进程（node / 浏览器）的环境：去掉指向本程序目录的 PATH 与打包器变量。

    否则子进程可能加载到我们 `_internal/` 里的 DLL（例如 VCRUNTIME140.dll），
    既污染对方，也会让后续部署因为文件被占用而失败。
    """
    env = os.environ.copy()
    if not getattr(sys, "frozen", False):
        return env
    blocked = {
        os.path.normcase(str(executable_dir())),
        os.path.normcase(str(executable_dir() / "_internal")),
    }
    entries = [
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if entry and os.path.normcase(entry) not in blocked
    ]
    if entries:
        env["PATH"] = os.pathsep.join(entries)
    else:
        env.pop("PATH", None)
    for name in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL"):
        env.pop(name, None)
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        if name in env:
            env.pop(name)
    return env
