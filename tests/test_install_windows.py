"""Windows 安装器：只创建主快捷方式，并清理旧的控制台入口。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dshlauncher.install import windows


def test_create_uses_tray_and_cleans_legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []
    monkeypatch.setattr(windows, "gui_command", lambda: (tmp_path / "dsh.exe", ""))
    monkeypatch.setattr(windows, "_run_powershell", lambda script: captured.append(script) or "")

    assert windows.create() == []
    script = captured[0]
    assert "New-Link 'dsh.lnk' 'tray'" in script
    assert "dsh 控制台.lnk" in script
    assert "New-Link 'dsh 控制台.lnk'" not in script
