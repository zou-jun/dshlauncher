"""kernelspec 的发现、注册、改名与删除（只动用户目录）。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ... import paths
from ...discovery import DiscoveryError
from .discovery import WINDOWS, Install

CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
#: 这些目录名不适合直接当 kernel id，向上再取一层。
VENV_NAMES = {".venv", "venv", "env", ".env"}


class KernelError(RuntimeError):
    """内核注册/删除前置条件不满足。"""


@dataclass(frozen=True)
class Kernel:
    name: str
    display_name: str
    language: str
    python: str
    resource_dir: Path
    managed: bool = False
    broken: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "language": self.language,
            "python": self.python,
            "resource_dir": str(self.resource_dir),
            "managed": self.managed,
            "broken": self.broken,
        }


def user_data_dir() -> Path:
    configured = os.environ.get("JUPYTER_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if WINDOWS:
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "jupyter"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Jupyter"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        if base:
            return Path(base) / "jupyter"
    return Path.home() / ".local" / "share" / "jupyter"


def user_kernels_dir() -> Path:
    return user_data_dir() / "kernels"


def kernel_dirs(install: Install) -> list[Path]:
    dirs: list[Path] = [user_kernels_dir()]
    if install.env is not None:
        dirs.append(install.env / "share" / "jupyter" / "kernels")
    for entry in os.environ.get("JUPYTER_PATH", "").split(os.pathsep):
        if entry.strip():
            dirs.append(Path(entry.strip()).expanduser() / "kernels")
    return dirs


def _read_spec(directory: Path, managed: dict[str, str]) -> Kernel | None:
    try:
        data = json.loads((directory / "kernel.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    argv = data.get("argv")
    python = str(argv[0]) if isinstance(argv, list) and argv else ""
    resolved = Path(python)
    broken = bool(python) and (resolved.is_absolute() and not resolved.is_file())
    return Kernel(
        name=directory.name,
        display_name=str(data.get("display_name") or directory.name),
        language=str(data.get("language") or ""),
        python=python,
        resource_dir=directory,
        managed=directory.name in managed,
        broken=broken,
    )


def list_kernels(install: Install, memory: dict) -> list[Kernel]:
    from .workdirs import managed as managed_map

    managed = managed_map(memory)
    seen: dict[str, Kernel] = {}
    for base in kernel_dirs(install):
        try:
            entries = sorted(path for path in base.iterdir() if path.is_dir())
        except OSError:
            continue
        for directory in entries:
            if directory.name in seen:
                continue
            spec = _read_spec(directory, managed)
            if spec is not None:
                seen[directory.name] = spec
    return sorted(seen.values(), key=lambda item: (item.name != "python3", item.name))


def find_kernel(install: Install, memory: dict, name: str) -> Kernel | None:
    for kernel in list_kernels(install, memory):
        if kernel.name == name:
            return kernel
    return None


def _run(args: list[str], *, timeout: float = 120.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            env=paths.child_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def validate_interpreter(python: Path) -> str:
    if not python.is_file():
        raise KernelError(f"解释器不存在：{python}")
    code, output = _run([str(python), "-c", "import sys; print(sys.version.split()[0])"], timeout=30)
    if code != 0:
        raise KernelError(f"不是可用的 Python 解释器：{python}\n{output.strip()}")
    code, output = _run([str(python), "-c", "import ipykernel"], timeout=30)
    if code != 0:
        raise KernelError(
            f"{python} 里没有 ipykernel。\n"
            f"项目环境：uv add ipykernel\n"
            f"或：uv pip install --python {python} ipykernel"
        )
    return output.strip()


def install_ipykernel(python: Path) -> str:
    uv = shutil.which("uv")
    if uv is None:
        for candidate in (
            Path.home() / ".local" / "bin" / ("uv.exe" if WINDOWS else "uv"),
            Path.home() / ".cargo" / "bin" / ("uv.exe" if WINDOWS else "uv"),
        ):
            if candidate.is_file():
                uv = str(candidate)
                break
    if uv is None:
        raise KernelError("找不到 uv，无法自动安装 ipykernel")
    code, output = _run([uv, "pip", "install", "--python", str(python), "ipykernel"], timeout=600)
    if code != 0:
        raise KernelError(f"安装 ipykernel 失败：\n{output.strip()}")
    return output.strip()


def _project_dir(python: Path) -> Path:
    parent = python.parent
    if parent.name.lower() in {"scripts", "bin"}:
        parent = parent.parent
    if parent.name.lower() in VENV_NAMES:
        parent = parent.parent
    return parent


def default_name(python: Path) -> str:
    parent = _project_dir(python)
    raw = parent.name.lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-._") or "python"
    if not slug[0].isalnum():
        slug = "python-" + slug
    return slug[:64]


def default_display(python: Path) -> str:
    return f"Python ({_project_dir(python).name})"


def add_kernel(
    install: Install,
    memory: dict,
    python: Path,
    *,
    name: str | None = None,
    display_name: str | None = None,
    replace: bool = False,
    install_dependency: bool = False,
) -> Kernel:
    python = python.expanduser()
    try:
        validate_interpreter(python)
    except KernelError:
        if not install_dependency:
            raise
        install_ipykernel(python)
        validate_interpreter(python)

    kernel_name = name or default_name(python)
    if not NAME_RE.match(kernel_name):
        raise KernelError(
            f"内核名称 {kernel_name!r} 不合法：只能用小写字母/数字/._-，最长 64，且以字母或数字开头"
        )
    label = display_name or default_display(python)
    existing = find_kernel(install, memory, kernel_name)
    if existing is not None and not replace:
        raise KernelError(
            f"内核 {kernel_name} 已存在（{existing.display_name}，{existing.resource_dir}）；"
            "确认覆盖请加 --replace"
        )

    command = [
        str(python),
        "-m",
        "ipykernel",
        "install",
        "--user",
        "--name",
        kernel_name,
        "--display-name",
        label,
    ]
    code, output = _run(command)
    if code != 0:
        raise KernelError(f"注册内核失败：\n{output.strip()}")
    spec = find_kernel(install, memory, kernel_name)
    if spec is None:
        raise KernelError(f"注册完成但找不到 kernelspec：{kernel_name}")
    return spec


def _ensure_user_spec(kernel: Kernel) -> None:
    user = user_kernels_dir().resolve()
    try:
        kernel.resource_dir.resolve().relative_to(user)
    except (OSError, ValueError) as exc:
        raise KernelError(
            f"{kernel.name} 不是用户内核（{kernel.resource_dir}），启动器只修改/删除用户目录下的内核"
        ) from exc


def rename_kernel(kernel: Kernel, display_name: str) -> Kernel:
    _ensure_user_spec(kernel)
    path = kernel.resource_dir / "kernel.json"
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KernelError(f"读取 {path} 失败：{exc}") from exc
    if not isinstance(data, dict):
        raise KernelError(f"{path} 不是对象")
    data["display_name"] = display_name
    paths.write_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return Kernel(
        kernel.name,
        display_name,
        kernel.language,
        kernel.python,
        kernel.resource_dir,
        kernel.managed,
        kernel.broken,
    )


def remove_kernel(kernel: Kernel) -> None:
    _ensure_user_spec(kernel)
    try:
        shutil.rmtree(kernel.resource_dir)
    except OSError as exc:
        raise KernelError(f"删除 {kernel.resource_dir} 失败：{exc}") from exc


def require_found(install: Install, memory: dict, name: str) -> Kernel:
    kernel = find_kernel(install, memory, name)
    if kernel is None:
        raise KernelError(f"没有名为 {name} 的内核；用 `kernel list` 查看")
    return kernel


def _discovery_error() -> type[DiscoveryError]:
    return DiscoveryError
