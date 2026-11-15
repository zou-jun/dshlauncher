"""服务状态文件 ``state.json``：原子读写。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import paths


@dataclass
class State:
    pid: int
    create_time: float
    port: int
    url: str | None = None


def read_state(path: Path) -> State | None:
    try:
        data = json.loads(path.read_text("utf-8"))
        return State(int(data["pid"]), float(data["create_time"]), int(data["port"]), data.get("url"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(path: Path, state: State) -> None:
    paths.write_atomic(path, json.dumps(asdict(state), indent=2))
