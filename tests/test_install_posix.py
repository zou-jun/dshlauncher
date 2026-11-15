"""POSIX 安装器：明确不支持创建入口，只清理旧文件。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dshlauncher.install import posix


def test_create_reports_unsupported() -> None:
    with pytest.raises(RuntimeError, match="不支持自动创建桌面入口"):
        posix.create()


def test_remove_cleans_legacy_desktop_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(posix, "_targets", lambda: [tmp_path])
    legacy = tmp_path / "dsh.desktop"
    legacy.write_text("", "utf-8")
    assert posix.remove() == [legacy]
    assert not legacy.exists()
