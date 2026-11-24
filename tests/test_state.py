"""state.json 的容错读取。"""

from __future__ import annotations

from pathlib import Path

from weblauncher.state import read_state


def test_non_object_state_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("[]", "utf-8")
    assert read_state(path) is None
