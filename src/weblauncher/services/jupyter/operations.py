"""Jupyter 配置用例：CLI 与 Web 控制台共用的内核/工作目录操作。

这里只改 ``memory`` 和 kernelspec 文件，不负责 HTTP/CLI 错误格式，
也不写 ``memory.toml``；调用方决定保存时机和错误展示。
"""

from __future__ import annotations

from pathlib import Path

from ... import memory as memory_mod
from . import kernels, workdirs
from .discovery import Install


class JupyterOperationError(RuntimeError):
    """参数不完整或动作不允许。"""


def resolve_python(
    *,
    directory: str | Path | None = None,
    python: str | Path | None = None,
) -> Path:
    """解析 ``--dir``/``--python``；目录只在标准 venv 位置查找。"""
    if directory:
        root = Path(directory).expanduser()
        if root.is_file():
            return root
        if not root.is_dir():
            raise JupyterOperationError(f"目录不存在：{root}")
        for candidate in (
            root / ".venv" / "Scripts" / "python.exe",
            root / ".venv" / "bin" / "python",
            root / "venv" / "Scripts" / "python.exe",
            root / "venv" / "bin" / "python",
        ):
            if candidate.is_file():
                return candidate
        raise JupyterOperationError(f"{root} 下没有找到 .venv/Scripts/python.exe 或 .venv/bin/python")
    if python:
        return Path(python).expanduser()
    raise JupyterOperationError("必须给出解释器路径，或包含 .venv 的项目目录")


def add_kernel(
    install: Install,
    memory: dict,
    *,
    directory: str | Path | None = None,
    python: str | Path | None = None,
    name: str | None = None,
    display_name: str | None = None,
    replace: bool = False,
    install_dependency: bool = False,
) -> kernels.Kernel:
    target = resolve_python(directory=directory, python=python)
    spec = kernels.add_kernel(
        install,
        memory,
        target,
        name=name,
        display_name=display_name,
        replace=replace,
        install_dependency=install_dependency,
    )
    workdirs.set_managed(memory, spec.name, spec.python)
    return spec


def select_kernel(
    install: Install, memory: dict, name: str, *, workdir: str | Path | None = None
) -> kernels.Kernel:
    spec = kernels.require_found(install, memory, name)
    if spec.broken:
        raise JupyterOperationError(f"内核 {spec.name} 的解释器不存在：{spec.python}")
    if workdir is not None:
        workdirs.remember(memory, Path(workdir), spec.name)
    return spec


def remove_kernel(install: Install, memory: dict, name: str, *, force: bool = False) -> kernels.Kernel:
    spec = kernels.require_found(install, memory, name)
    if not spec.managed and not force:
        raise JupyterOperationError(
            f"{spec.name} 不是启动器注册的内核；确认删除请使用强制删除\n  {spec.resource_dir}"
        )
    kernels.remove_kernel(spec)
    table = memory_mod.section(memory, "jupyter")
    if table.get("kernel") == spec.name:
        memory_mod.set_value(memory, "jupyter", "kernel", None)
    mapping = table.get("workdir_kernels")
    if isinstance(mapping, dict):
        for key, value in list(mapping.items()):
            if value == spec.name:
                mapping.pop(key, None)
    workdirs.set_managed(memory, spec.name, None)
    return spec


def select_workdir(
    install: Install | None,
    memory: dict,
    value: str | Path,
    *,
    kernel: str | None = None,
) -> Path:
    workdir = workdirs.normalize(value)
    if kernel:
        if install is None:
            raise JupyterOperationError("选择内核前需要先定位 Jupyter Lab")
        select_kernel(install, memory, kernel)
    workdirs.remember(memory, workdir, kernel)
    return workdir
