"""平台原生弹窗的命令选择（不真的启动桌面工具）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dshlauncher.platform import linux, posix


def _recorder(calls: list[list[str]]):  # noqa: ANN202 - 测试辅助
    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    return run


def test_linux_prefers_zenity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(linux.subprocess, "run", _recorder(calls))
    linux.message("T", "body")
    assert calls == [["zenity", "--info", "--no-markup", "--title", "T", "--text", "body"]]


def test_linux_error_uses_error_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    monkeypatch.setattr(linux.subprocess, "run", _recorder(calls))
    linux.message("T", "body", error=True)
    assert "--error" in calls[0]
    assert "--info" not in calls[0]


def test_linux_falls_back_to_kdialog(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(linux.shutil, "which", lambda name: "/usr/bin/kdialog" if name == "kdialog" else None)
    monkeypatch.setattr(linux.subprocess, "run", _recorder(calls))
    linux.message("T", "body")
    assert calls == [["kdialog", "--title", "T", "--msgbox", "body"]]


def test_linux_falls_back_to_notify_send(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(linux.shutil, "which", lambda name: None)
    monkeypatch.setattr(linux.subprocess, "run", _recorder(calls))
    linux.message("T", "body", error=True)
    assert calls == [["notify-send", "--urgency=critical", "T", "body"]]


def test_posix_uses_osascript_and_escapes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        posix.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None
    )
    monkeypatch.setattr(posix.subprocess, "run", _recorder(calls))
    posix.message('a"b', "line\\next", error=True)
    command = calls[0]
    assert command[:2] == ["osascript", "-e"]
    assert 'a\\"b' in command[2]
    assert "line\\\\next" in command[2]
    assert command[2].endswith("as critical")


def test_posix_falls_back_to_notify_send(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(posix.shutil, "which", lambda name: None)
    monkeypatch.setattr(posix.subprocess, "run", _recorder(calls))
    posix.message("T", "body")
    assert calls == [["notify-send", "T", "body"]]
