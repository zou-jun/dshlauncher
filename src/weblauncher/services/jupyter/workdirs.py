"""Jupyter 工作目录：校验、最近目录与会话内记忆。"""

from __future__ import annotations

from pathlib import Path

from ... import memory as memory_mod

RECENT_LIMIT = 10


class WorkdirError(RuntimeError):
    """工作目录不可用。"""


def normalize(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise WorkdirError(f"无法解析目录 {value!r}：{exc}") from exc
    if not resolved.exists():
        raise WorkdirError(f"目录不存在：{resolved}")
    if not resolved.is_dir():
        raise WorkdirError(f"不是目录：{resolved}")
    return resolved


def recent(memory: dict) -> list[Path]:
    table = memory_mod.section(memory, "jupyter")
    values = table.get("recent_workdirs")
    if not isinstance(values, list):
        return []
    result: list[Path] = []
    for value in values:
        if isinstance(value, str) and value:
            result.append(Path(value))
    return result


def remember(memory: dict, workdir: Path, kernel: str | None = None) -> None:
    """记录本次选择；成功启动后调用，失败不覆盖既有记忆。"""
    resolved = normalize(workdir)
    table = memory_mod.section(memory, "jupyter")
    recents: list[str] = [str(resolved)]
    for value in table.get("recent_workdirs", []):
        if not isinstance(value, str) or not value:
            continue
        try:
            same = Path(value).expanduser().resolve() == resolved
        except OSError:
            same = Path(value) == resolved
        if not same and len(recents) < RECENT_LIMIT:
            recents.append(value)
    memory_mod.set_value(memory, "jupyter", "recent_workdirs", recents)
    memory_mod.set_value(memory, "jupyter", "workdir", str(resolved))
    if kernel:
        memory_mod.set_value(memory, "jupyter", "kernel", kernel)
        if table.get("remember_per_workdir", True) is not False:
            raw_mapping = table.get("workdir_kernels")
            mapping = dict(raw_mapping) if isinstance(raw_mapping, dict) else {}
            mapping[str(resolved)] = kernel
            memory_mod.set_value(memory, "jupyter", "workdir_kernels", mapping)


def remember_kernel(memory: dict, kernel: str) -> None:
    memory_mod.set_value(memory, "jupyter", "kernel", kernel)


def managed(memory: dict) -> dict[str, str]:
    table = memory_mod.section(memory, "jupyter")
    value = table.get("managed_kernels")
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if isinstance(item, str)}


def set_managed(memory: dict, name: str, python: str | None) -> None:
    table = memory_mod.section(memory, "jupyter")
    value = table.get("managed_kernels")
    mapping = dict(value) if isinstance(value, dict) else {}
    if python:
        mapping[name] = python
    else:
        mapping.pop(name, None)
    memory_mod.set_value(memory, "jupyter", "managed_kernels", mapping)
