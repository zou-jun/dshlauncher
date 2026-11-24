"""open_dsh 的过场路径：服务未就绪先开本地页，就绪后 ready。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from weblauncher import actions
from weblauncher.paths import Paths
from weblauncher.services.dsh.settings import Settings
from weblauncher.state import State


class FakeSplash:
    instances: list[FakeSplash] = []

    def __init__(self, title: str = "服务") -> None:
        self.url = "http://127.0.0.1:1/splash/"
        self.started = False
        self.ready_url: str | None = None
        self.failed: str | None = None
        self.closed: float | str | None = None
        self.waited: float | None = None
        FakeSplash.instances.append(self)

    def start(self) -> None:
        self.started = True

    def ready(self, url: str) -> None:
        self.ready_url = url

    def fail(self, message: str) -> None:
        self.failed = message

    def wait_delivered(self, timeout: float) -> bool:
        self.waited = timeout
        return True

    def close(self) -> None:
        self.closed = "now"

    def close_later(self, delay: float) -> None:
        self.closed = delay


def _context(tmp_path: Path, controller: object) -> Any:
    return SimpleNamespace(
        settings=Settings(),
        paths=Paths(tmp_path),
        backend=object(),
        service_id="dsh",
        spec=SimpleNamespace(use_splash=True, label="dsh web"),
        service=lambda: controller,
    )


@pytest.fixture(autouse=True)
def _reset_splash() -> None:
    FakeSplash.instances.clear()


def test_open_uses_splash_when_service_not_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = State(pid=9, create_time=1.0, port=18080, url="http://dsh/?token=x")
    controller = SimpleNamespace(
        read_state=lambda: None,
        live_process=lambda value: None,
        ensure=lambda: (state, True),
        latest_url=lambda: None,
    )
    launches: list[tuple[str, dict[str, object]]] = []

    def fake_launch(settings: Settings, url: str, **kwargs: object) -> str:
        launches.append((url, kwargs))
        return "new"

    monkeypatch.setattr(actions, "SplashServer", FakeSplash)
    monkeypatch.setattr(actions.browser, "launch", fake_launch)

    result = actions.open_service(_context(tmp_path, controller))

    splash = FakeSplash.instances[-1]
    assert splash.started
    assert len(launches) == 1
    assert launches[0][0] == splash.url
    assert launches[0][1]["dedupe"] is False
    assert splash.ready_url == state.url
    assert splash.closed == 1.0
    assert "pid=9 started=True" in result


def test_open_keeps_splash_alive_when_page_has_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = State(pid=9, create_time=1.0, port=18080, url="http://dsh/?token=x")
    controller = SimpleNamespace(
        read_state=lambda: None,
        live_process=lambda value: None,
        ensure=lambda: (state, True),
        latest_url=lambda: None,
    )
    monkeypatch.setattr(actions, "SplashServer", FakeSplash)
    monkeypatch.setattr(actions.browser, "launch", lambda settings, url, **kwargs: "new")
    monkeypatch.setattr(FakeSplash, "wait_delivered", lambda self, timeout: False)

    actions.open_service(_context(tmp_path, controller))

    assert FakeSplash.instances[-1].closed == 30.0


def test_open_skips_splash_when_service_already_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = State(pid=9, create_time=1.0, port=18080, url="http://dsh/?token=x")
    controller = SimpleNamespace(
        read_state=lambda: state,
        live_process=lambda value: object(),
        ensure=lambda: (_ for _ in ()).throw(AssertionError("不应重启")),
        latest_url=lambda: None,
    )
    calls: list[str] = []

    def fake_launch(settings: Settings, url: str, **kwargs: object) -> str:
        calls.append(url)
        return "focused"

    monkeypatch.setattr(actions, "SplashServer", FakeSplash)
    monkeypatch.setattr(actions.browser, "launch", fake_launch)

    result = actions.open_service(_context(tmp_path, controller))

    assert FakeSplash.instances == []
    assert len(calls) == 1
    assert calls[0].startswith("http://127.0.0.1:")
    assert state.url is not None and state.url not in calls[0]
    assert "started=False" in result


def test_open_shows_startup_error_in_splash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> tuple[State, bool]:
        raise RuntimeError("startup failed")

    controller = SimpleNamespace(
        read_state=lambda: None,
        live_process=lambda value: None,
        ensure=boom,
        latest_url=lambda: None,
    )
    monkeypatch.setattr(actions, "SplashServer", FakeSplash)
    monkeypatch.setattr(actions.browser, "launch", lambda settings, url, **kwargs: "new")

    with pytest.raises(RuntimeError, match="startup failed"):
        actions.open_service(_context(tmp_path, controller))

    splash = FakeSplash.instances[-1]
    assert splash.failed and "startup failed" in splash.failed
    assert splash.closed == 30.0
