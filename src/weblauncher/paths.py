"""运行时数据目录与文件位置。

数据默认放在可执行文件同级的 `.weblauncher/`；源码运行时即项目根目录下的
`.weblauncher/`。目标位置不可写（例如 exe 装在 Program Files）时回退到当前
用户的数据目录，可用 `WEBLAUNCHER_HOME` 强制指定。
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
from typing import BinaryIO, Literal, TextIO, overload

DATA_DIR_NAME = ".weblauncher"
LEGACY_DATA_DIR_NAME = ".dshlauncher"
SERVICES_DIR = "services"
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


def _user_data_dir(name: str = "weblauncher") -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / name
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / name
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / name
    return Path.home() / ".local" / "state" / name


def _migrate_dir(old: Path, new: Path) -> None:
    """把旧品牌的数据目录整体搬到新名字；失败时不阻断启动。"""
    if not old.exists() or new.exists():
        return
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
    except OSError:
        import shutil

        with contextlib.suppress(OSError):
            shutil.move(str(old), str(new))


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", "utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            path.chmod(0o700)


@overload
def open_append(path: Path, *, binary: Literal[True]) -> BinaryIO: ...


@overload
def open_append(path: Path, *, binary: Literal[False] = False) -> TextIO: ...


def open_append(path: Path, *, binary: bool = False) -> BinaryIO | TextIO:
    """打开运行日志：新文件 0600，已有文件也收紧到 0600（POSIX）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    if os.name != "nt":
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    if binary:
        return os.fdopen(fd, "ab", buffering=0)
    return os.fdopen(fd, "a", encoding="utf-8")


@lru_cache(maxsize=1)
def data_dir() -> Path:
    override = os.environ.get("WEBLAUNCHER_HOME")
    if override:
        path = Path(override).expanduser().resolve()
        _mkdir_private(path)
        return path
    beside_exe = executable_dir() / DATA_DIR_NAME
    legacy_fallback = _user_data_dir("dshlauncher")
    _migrate_dir(executable_dir() / LEGACY_DATA_DIR_NAME, beside_exe)
    if not beside_exe.exists():
        # 旧版 exe 在 Program Files 时会落到用户目录；新版若可写，应优先把它带过来。
        _migrate_dir(legacy_fallback, beside_exe)
    if _writable(beside_exe):
        _mkdir_private(beside_exe)
        return beside_exe
    fallback = _user_data_dir()
    _migrate_dir(legacy_fallback, fallback)
    _mkdir_private(fallback)
    return fallback


def ensure_data_dir() -> Path:
    path = data_dir()
    _mkdir_private(path)
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
class ServicePaths:
    """单个服务的状态、日志与浏览器配置目录。"""

    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def log(self) -> Path:
        return self.root / "service.log"

    @property
    def lock(self) -> Path:
        return self.root / "service.lock"

    @property
    def profile(self) -> Path:
        return self.root / "browser"

    def ensure(self) -> Path:
        _mkdir_private(self.root)
        return self.root


@dataclass(frozen=True)
class Paths:
    """一个数据目录下的全部运行时文件；测试/嵌入可显式注入。"""

    data: Path

    @classmethod
    def current(cls) -> Paths:
        return cls(data_dir())

    def ensure(self) -> Path:
        _mkdir_private(self.data)
        return self.data

    def migrate_legacy(self) -> list[str]:
        """把单服务布局搬到 ``services/dsh/``；幂等，失败只记录不阻断。"""
        import shutil

        moved: list[str] = []
        service = self.service("dsh")
        pairs = (
            (self.data / "state.json", service.state),
            (self.data / "dsh-web.log", service.log),
        )
        for old, new in pairs:
            if not old.exists() or new.exists():
                continue
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                old.replace(new)
                moved.append(f"{old.name} → {new.relative_to(self.data)}")
            except OSError:
                continue
        old_profile = self.data / "browser"
        if old_profile.is_dir() and not service.profile.exists():
            try:
                service.profile.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_profile), str(service.profile))
                moved.append(f"browser/ → {service.profile.relative_to(self.data)}")
            except OSError:
                pass
        if moved:
            self.audit("迁移旧数据布局: " + "; ".join(moved))
        return moved

    def service(self, service_id: str) -> ServicePaths:
        return ServicePaths(self.data / SERVICES_DIR / service_id)

    #: dsh 的历史属性；新代码应使用 ``service("dsh")``。
    @property
    def state(self) -> Path:
        return self.service("dsh").state

    @property
    def log(self) -> Path:
        return self.service("dsh").log

    @property
    def memory(self) -> Path:
        return self.data / "memory.toml"

    @property
    def launcher_log(self) -> Path:
        return self.data / "launcher.log"

    @property
    def upgrades_log(self) -> Path:
        """升级任务完整日志；面板内存里只保留尾部。"""
        return self.data / "upgrades.log"

    @property
    def profile(self) -> Path:
        return self.service("dsh").profile

    @property
    def control_profile(self) -> Path:
        """控制台使用独立 Chromium 配置，避免和普通浏览器扩展共用会话。"""
        return self.data / "control-browser"

    @property
    def tabbed_profile(self) -> Path:
        """单窗口模式：控制台与所有服务共用的 Chromium 配置。"""
        return self.data / "tabbed-browser"

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
            with open_append(log) as handle:
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


def tabbed_profile() -> Path:
    return Paths.current().tabbed_profile


def config_path() -> Path:
    return Paths.current().config


def memory_path() -> Path:
    return Paths.current().memory


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
