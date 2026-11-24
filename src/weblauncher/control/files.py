"""控制台的目录浏览/文件选择 API。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import ControlError


def list_dir(value: str, *, include_files: bool = False) -> dict[str, Any]:
    if not value:
        if os.name == "nt":
            entries = []
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = Path(f"{letter}:\\")
                if drive.exists():
                    entries.append({"name": f"{letter}:\\", "path": str(drive), "dir": True})
            return {"path": "", "parent": None, "entries": entries}
        value = str(Path.home())
    path = Path(value).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ControlError(f"无法解析目录：{exc}") from exc
    if resolved.is_file():
        resolved = resolved.parent
    if not resolved.is_dir():
        raise ControlError(f"目录不存在：{resolved}", status=404)
    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(resolved.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            try:
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child), "dir": True})
                elif include_files:
                    entries.append({"name": child.name, "path": str(child), "dir": False})
            except OSError:
                continue
    except OSError as exc:
        raise ControlError(f"无法读取目录：{exc}") from exc
    parent = str(resolved.parent) if resolved.parent != resolved else None
    return {"path": str(resolved), "parent": parent, "entries": entries}


__all__ = ["list_dir"]
