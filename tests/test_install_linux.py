"""Linux 安装器：入口直接运行 tray，只写应用菜单。"""

from __future__ import annotations

from pathlib import Path

import pytest

from weblauncher.install import linux


def test_entry_runs_tray(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linux, "applications_dir", lambda: tmp_path)
    monkeypatch.setattr(linux, "_desktop_dirs", lambda: [tmp_path / "desktop"])
    monkeypatch.setattr(linux, "install_icons", lambda icon: {})
    monkeypatch.setattr(linux, "gui_command", lambda: ["/usr/bin/python3", "-m", "weblauncher"])

    written = linux.create()
    entry = tmp_path / "weblauncher.desktop"
    assert entry in written
    text = entry.read_text("utf-8")
    assert "Exec=/usr/bin/python3 -m weblauncher ui" in text
    assert "Name=Web 服务启动器" in text
    assert (tmp_path / "dsh.desktop").is_file()
    assert (tmp_path / "jupyter.desktop").is_file()


def test_install_removes_legacy_application_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(linux, "applications_dir", lambda: tmp_path)
    monkeypatch.setattr(linux, "_desktop_dirs", lambda: [])
    monkeypatch.setattr(linux, "install_icons", lambda icon: {})
    monkeypatch.setattr(linux, "gui_command", lambda: ["/usr/bin/python3", "-m", "weblauncher"])
    legacy = tmp_path / "dsh-ui.desktop"
    legacy.write_text("old", "utf-8")
    linux.create()
    assert not legacy.exists()
    assert (tmp_path / "weblauncher.desktop").exists()


def test_create_uses_per_app_icons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    icons = {
        "control": tmp_path / "control.png",
        "dsh": tmp_path / "dsh.png",
        "jupyter": tmp_path / "jupyter.png",
    }
    monkeypatch.setattr(linux, "applications_dir", lambda: tmp_path)
    monkeypatch.setattr(linux, "_desktop_dirs", lambda: [])
    monkeypatch.setattr(linux, "install_icons", lambda icon: icons)
    monkeypatch.setattr(linux, "gui_command", lambda: ["/usr/bin/python3", "-m", "weblauncher"])

    linux.create()
    assert f"Icon={icons['control']}" in (tmp_path / "weblauncher.desktop").read_text("utf-8")
    assert f"Icon={icons['dsh']}" in (tmp_path / "dsh.desktop").read_text("utf-8")
    assert f"Icon={icons['jupyter']}" in (tmp_path / "jupyter.desktop").read_text("utf-8")
