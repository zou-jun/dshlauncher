"""服务状态文件 ``state.json``：原子读写。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import paths


@dataclass
class State:
    pid: int
    create_time: float
    port: int
    url: str | None = None
    token: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def read_state(path: Path) -> State | None:
    try:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            return None
        extra = data.get("extra")
        return State(
            int(data["pid"]),
            float(data["create_time"]),
            int(data["port"]),
            data.get("url"),
            data.get("token"),
            extra if isinstance(extra, dict) else {},
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(path: Path, state: State) -> None:
    paths.write_atomic(path, json.dumps(asdict(state), indent=2))
