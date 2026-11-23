"""运行时数据目录与文件位置。

数据默认放在可执行文件同级的 `.dshlauncher/`；源码运行时即项目根目录下的
`.dshlauncher/`。目标位置不可写（例如 exe 装在 Program Files）时回退到当前
用户的数据目录，可用 `DSHLAUNCHER_HOME` 强制指定。
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

DATA_DIR_NAME = ".dshlauncher"
AUDIT_ROTATE_BYTES = 1024 * 1024


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


def write_atomic(path: Path, text: str) -> None:
    """先写同目录临时文件再 replace：读者永远看不到半个 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


@dataclass(frozen=True)
class Paths:
    """一个数据目录下的全部运行时文件；测试/嵌入可显式注入。"""

    data: Path

    @classmethod
    def current(cls) -> Paths:
        return cls(data_dir())

    def ensure(self) -> Path:
        self.data.mkdir(parents=True, exist_ok=True)
        return self.data

    @property
    def state(self) -> Path:
        return self.data / "state.json"

    @property
    def log(self) -> Path:
        return self.data / "dsh-web.log"

    @property
    def launcher_log(self) -> Path:
        return self.data / "launcher.log"

    @property
    def upgrades_log(self) -> Path:
        """升级任务完整日志；面板内存里只保留尾部。"""
        return self.data / "upgrades.log"

    @property
    def profile(self) -> Path:
        return self.data / "browser"

    @property
    def panel_profile(self) -> Path:
        """更新面板使用独立 Chromium 配置，避免和 dsh 应用窗口抢同一实例。"""
        return self.data / "panel-browser"

    @property
    def config(self) -> Path:
        return self.data / "config.toml"

    @property
    def tray_info(self) -> Path:
        return self.data / "tray.json"

    @property
    def tray_lock(self) -> Path:
        return self.data / "tray.lock"

    def audit(self, text: str, *, detail: str | None = None) -> None:
        """追加一行启动器审计日志（GUI 启动时唯一可发现的记录）。

        ``detail`` 用于异常摘要：换行会被压成 `` | ``，保留调用点但不刷屏。
        """
        try:
            self.ensure()
            log = self.launcher_log
            _rotate_audit(log)
            line = text.splitlines()[0] if text else ""
            if detail:
                rows = [row.strip() for row in detail.splitlines() if row.strip()]
                line += " | " + " | ".join(rows)[:1000]
            with log.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
        except OSError:
            pass


def state_path() -> Path:
    return Paths.current().state


def log_path() -> Path:
    return Paths.current().log


def launcher_log_path() -> Path:
    return Paths.current().launcher_log


def profile_dir() -> Path:
    return Paths.current().profile


def config_path() -> Path:
    return Paths.current().config


def audit(text: str, *, detail: str | None = None) -> None:
    Paths.current().audit(text, detail=detail)


def _rotate_audit(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > AUDIT_ROTATE_BYTES:
            rotated = path.with_name(path.name + ".1")
            rotated.unlink(missing_ok=True)
            path.replace(rotated)
    except OSError:
        pass


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
    for name in (
        "_MEIPASS2",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_ARCHIVE_FILE",
        "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_LINUX_PROCESS_NAME",
    ):
        env.pop(name, None)
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
        if name in env:
            env.pop(name)
    return env
