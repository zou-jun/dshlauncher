"""启动器写的选择记忆（``memory.toml``）。

与 ``config.toml`` 分开：配置文件允许手写并保留注释，这份文件只由启动器
原子重写，用来记住“上次选的工作目录 / 内核 / 最近目录”。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from . import paths as paths_mod

TOML_SCALAR = (str, int, float, bool)


def load(path: Path | None = None) -> dict[str, Any]:
    try:
        with (path or paths_mod.memory_path()).open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _key(value: str) -> str:
    if value and all(char.isalnum() or char in "_-" for char in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"memory.toml 不支持的值：{value!r}")


def dumps(data: dict[str, Any]) -> str:
    """只支持本项目用到的形状：标量、字符串列表、一层子表。"""
    lines: list[str] = []

    def emit(table: dict[str, Any], prefix: str = "") -> None:
        scalars = {key: value for key, value in table.items() if not isinstance(value, dict)}
        children = {key: value for key, value in table.items() if isinstance(value, dict)}
        for key, value in scalars.items():
            lines.append(f"{_key(key)} = {_value(value)}")
        for key, value in children.items():
            heading = f"{prefix}{_key(key)}"
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"[{heading}]")
            emit(value, prefix=heading + ".")

    emit(data)
    return "\n".join(lines).strip() + "\n"


def save(data: dict[str, Any], path: Path | None = None) -> Path:
    target = path or paths_mod.memory_path()
    paths_mod.write_atomic(target, dumps(data))
    return target


def section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return value if isinstance(value, dict) else {}


def get(data: dict[str, Any], service: str, key: str, default: Any = None) -> Any:
    return section(data, service).get(key, default)


def set_value(data: dict[str, Any], service: str, key: str, value: Any) -> None:
    target = data.setdefault(service, {})
    if not isinstance(target, dict):
        target = {}
        data[service] = target
    if value is None:
        target.pop(key, None)
        return
    target[key] = value
