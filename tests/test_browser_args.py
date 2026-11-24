from pathlib import Path

import pytest

from weblauncher import browser, discovery
from weblauncher.geometry import Rect
from weblauncher.services.dsh.settings import Settings

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


def test_launch_can_force_new_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    found: list[set[int]] = []

    class Backend:
        def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]:
            return {"creationflags": 0}

        def process_names(self, browser: str) -> set[str]:
            return {"chrome.exe"}

        def supports_window_control(self, ozone: str | None = None) -> bool:
            return True

        def work_area(self) -> None:
            return None

        def find_window(self, pids: set[int]) -> int:
            found.append(pids)
            return 1

    monkeypatch.setattr(browser.platform, "load", lambda: Backend())
    monkeypatch.setattr(
        browser.discovery,
        "browser_exe",
        lambda value: discovery.Browser("chrome", Path("chrome.exe")),
    )
    monkeypatch.setattr(browser, "_wait_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "_profile_pids", lambda *args: set())
    monkeypatch.setattr(browser.paths, "child_env", lambda: {})
    monkeypatch.setattr(browser.subprocess, "Popen", lambda *args, **kwargs: calls.append(kwargs))

    settings = Settings(profile_dir=tmp_path / "browser", dedupe=True)
    assert browser.launch(settings, "http://x", dedupe=False) == "new"
    assert found == []
    assert calls


def test_single_window_first_launch_uses_normal_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    class Backend:
        def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]:
            return {"creationflags": 0}

        def process_names(self, browser: str) -> set[str]:
            return {"chrome.exe"}

        def supports_window_control(self, ozone: str | None = None) -> bool:
            return True

        def work_area(self) -> None:
            return None

    monkeypatch.setattr(browser.platform, "load", lambda: Backend())
    monkeypatch.setattr(
        browser.discovery,
        "browser_exe",
        lambda value: discovery.Browser("chrome", Path("chrome.exe")),
    )
    monkeypatch.setattr(browser, "_profile_pids", lambda *args: set())
    monkeypatch.setattr(browser, "_wait_window", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser.paths, "child_env", lambda: {})
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: calls.append(args))

    settings = Settings(profile_dir=tmp_path / "browser", single_window=True)
    assert browser.launch(settings, "http://127.0.0.1:1/") == "new"
    args = calls[0]
    assert not any(arg.startswith("--app=") for arg in args)
    assert "--new-window" in args
    assert args[-1] == "http://127.0.0.1:1/"


def test_single_window_existing_profile_appends_tab(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class Backend:
        def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]:
            return {"creationflags": 0}

        def process_names(self, browser: str) -> set[str]:
            return {"chrome.exe"}

        def supports_window_control(self, ozone: str | None = None) -> bool:
            return True

        def work_area(self) -> None:
            return None

    monkeypatch.setattr(browser.platform, "load", lambda: Backend())
    monkeypatch.setattr(
        browser.discovery,
        "browser_exe",
        lambda value: discovery.Browser("chrome", Path("chrome.exe")),
    )
    monkeypatch.setattr(browser, "_profile_pids", lambda *args: {1})
    monkeypatch.setattr(browser.paths, "child_env", lambda: {})
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: calls.append(args))

    settings = Settings(profile_dir=tmp_path / "browser", single_window=True)
    assert browser.launch(settings, "http://127.0.0.1:2/") == "tab"
    args = calls[0]
    assert not any(arg.startswith("--app=") for arg in args)
    assert "--new-window" not in args
    assert args[-1] == "http://127.0.0.1:2/"


def test_single_window_daily_profile_omits_user_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    class Backend:
        def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]:
            return {"creationflags": 0}

        def process_names(self, browser: str) -> set[str]:
            return {"chrome.exe"}

        def supports_window_control(self, ozone: str | None = None) -> bool:
            return True

        def work_area(self) -> None:
            return None

    monkeypatch.setattr(browser.platform, "load", lambda: Backend())
    monkeypatch.setattr(
        browser.discovery,
        "browser_exe",
        lambda value: discovery.Browser("chrome", Path("chrome.exe")),
    )
    monkeypatch.setattr(browser, "_default_profile_pids", lambda *args: set())
    monkeypatch.setattr(browser.paths, "child_env", lambda: {})
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: calls.append(args))

    settings = Settings(profile_dir=tmp_path / "browser", single_window=True, daily_profile=True)
    assert browser.launch(settings, "http://127.0.0.1:3/") == "new"
    args = calls[0]
    assert not any(arg.startswith("--user-data-dir=") for arg in args)
    assert "--disable-sync" not in args
    assert "--new-window" in args
    assert args[-1] == "http://127.0.0.1:3/"


def test_single_window_daily_profile_reuses_open_chrome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    class Backend:
        def detach_kwargs(self, *, breakaway: bool = True) -> dict[str, int]:
            return {"creationflags": 0}

        def process_names(self, browser: str) -> set[str]:
            return {"chrome.exe"}

        def supports_window_control(self, ozone: str | None = None) -> bool:
            return True

        def work_area(self) -> None:
            return None

    monkeypatch.setattr(browser.platform, "load", lambda: Backend())
    monkeypatch.setattr(
        browser.discovery,
        "browser_exe",
        lambda value: discovery.Browser("chrome", Path("chrome.exe")),
    )
    monkeypatch.setattr(browser, "_default_profile_pids", lambda *args: {1})
    monkeypatch.setattr(browser.paths, "child_env", lambda: {})
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: calls.append(args))

    settings = Settings(profile_dir=tmp_path / "browser", single_window=True, daily_profile=True)
    assert browser.launch(settings, "http://127.0.0.1:4/") == "tab"
    args = calls[0]
    assert not any(arg.startswith("--user-data-dir=") for arg in args)
    assert "--new-window" not in args
    assert args[-1] == "http://127.0.0.1:4/"
