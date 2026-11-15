"""Linux 安装器：入口直接运行 tray，只写应用菜单。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dshlauncher.install import linux


def test_entry_runs_tray(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linux, "applications_dir", lambda: tmp_path)
    monkeypatch.setattr(linux, "_desktop_dirs", lambda: [tmp_path / "desktop"])
    monkeypatch.setattr(linux, "install_icon", lambda icon: None)
    monkeypatch.setattr(linux, "gui_command", lambda: ["/usr/bin/python3", "-m", "dshlauncher"])

    written = linux.create()
    entry = tmp_path / "dsh.desktop"
    assert entry in written
    text = entry.read_text("utf-8")
    assert "Exec=/usr/bin/python3 -m dshlauncher tray" in text
    assert "Name=dsh" in text
