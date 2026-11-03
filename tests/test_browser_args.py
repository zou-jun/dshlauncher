from pathlib import Path

import pytest

from dshlauncher import browser, discovery
from dshlauncher.geometry import Rect
from dshlauncher.settings import Settings

CHROME = discovery.Browser("chrome", Path("/usr/bin/google-chrome-stable"))
TARGET = Rect(10, 20, 800, 600)


def _settings(ozone: str) -> Settings:
    return Settings(ozone=ozone, profile_dir=Path("/tmp/dsh-profile"))


def test_x11_passes_platform_and_position(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser.sys, "platform", "linux")
    args = browser.build_args(
        _settings("x11"), CHROME, "http://127.0.0.1:1/?token=x", TARGET, window_control=True
    )
    assert "--ozone-platform=x11" in args
    assert "--window-size=800,600" in args
    assert "--window-position=10,20" in args


def test_native_wayland_has_size_but_no_position(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser.sys, "platform", "linux")
    args = browser.build_args(
        _settings("auto"), CHROME, "http://127.0.0.1:1/?token=x", TARGET, window_control=False
    )
    assert not any(arg.startswith("--ozone-platform") for arg in args)
    assert "--window-size=800,600" in args
    assert not any(arg.startswith("--window-position") for arg in args)


def test_ozone_flag_only_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser.sys, "platform", "win32")
    assert browser.ozone_args(_settings("x11")) == []
