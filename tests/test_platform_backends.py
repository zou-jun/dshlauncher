import pytest

from dshlauncher import platform as platform_mod
from dshlauncher.geometry import Rect
from dshlauncher.platform import linux, posix
from dshlauncher.platform import windows as windows_mod


def test_load_follows_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DSHLAUNCHER_WINDOW_BACKEND", raising=False)
    monkeypatch.setattr(platform_mod.sys, "platform", "linux")
    assert platform_mod.load() is linux
    monkeypatch.setattr(platform_mod.sys, "platform", "win32")
    assert platform_mod.load() is windows_mod
    monkeypatch.setattr(platform_mod.sys, "platform", "darwin")
    assert platform_mod.load() is posix


def test_explicit_backend_overrides_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_mod.sys, "platform", "linux")
    monkeypatch.setenv("DSHLAUNCHER_WINDOW_BACKEND", "posix")
    assert platform_mod.load() is posix


def test_macos_backend_has_no_window_control() -> None:
    assert posix.supports_window_control("x11") is False


def test_workarea_picks_current_desktop() -> None:
    raw = b"".join(value.to_bytes(4, "little") for value in (0, 32, 1920, 1048, 10, 20, 500, 400))
    assert linux._work_area_values(raw, 1) == Rect(10, 20, 500, 400)


def test_workarea_short_list_uses_first_desktop() -> None:
    raw = b"".join(value.to_bytes(4, "little") for value in (0, 32, 1920, 1048))
    assert linux._work_area_values(raw, 3) == Rect(0, 32, 1920, 1048)


def test_workarea_rejects_empty() -> None:
    assert linux._work_area_values(b"", 0) is None
