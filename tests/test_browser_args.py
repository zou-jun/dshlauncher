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


def test_launch_falls_back_when_breakaway_denied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_popen(args, **kwargs):  # noqa: ANN001, ANN202 - 只记录参数
        calls.append(kwargs)
        if kwargs.get("creationflags", 0) & 0x01000000:
            raise PermissionError(5, "拒绝访问")
        return object()

    class Backend:
        def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]:
            flags = 0x00000008
            return {"creationflags": flags | (0x01000000 if breakaway else 0)}

        def process_names(self, browser: str) -> set[str]:
            return {"chrome.exe"}

        def supports_window_control(self, ozone: str | None = None) -> bool:
            return False

        def work_area(self) -> None:
            return None

    monkeypatch.setattr(browser.platform, "load", lambda: Backend())
    monkeypatch.setattr(
        browser.discovery,
        "browser_exe",
        lambda value: discovery.Browser("chrome", Path("chrome.exe")),
    )
    monkeypatch.setattr(browser.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(browser.paths, "child_env", lambda: {})

    settings = Settings(dedupe=False, profile_dir=tmp_path / "browser")
    assert browser.launch(settings, "http://127.0.0.1:1/?token=x") == "new"
    assert len(calls) == 2
    assert calls[0]["creationflags"] & 0x01000000
    assert not calls[1]["creationflags"] & 0x01000000
