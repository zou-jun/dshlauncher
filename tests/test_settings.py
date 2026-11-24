import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from weblauncher import paths
from weblauncher.services.dsh import settings


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("WEBLAUNCHER_HOME", str(tmp_path))
    for name in ("PORT", "HOST", "CWD", "BROWSER", "NO_DEDUPE"):
        monkeypatch.delenv("WEBLAUNCHER_DSH_" + name, raising=False)
    monkeypatch.delenv("WEBLAUNCHER_SINGLE_WINDOW", raising=False)
    monkeypatch.delenv("WEBLAUNCHER_SINGLE_WINDOW_PROFILE", raising=False)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def test_defaults(isolated_home: Path) -> None:
    loaded = settings.load()
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 3080
    assert loaded.work_dir == Path(tempfile.gettempdir())
    assert loaded.dedupe is True
    assert loaded.single_window is False


def test_file_beats_default_and_env_beats_file(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated_home / "config.toml").write_text('port = 4000\nhost = "0.0.0.0"\n', "utf-8")
    assert settings.load().port == 4000
    assert settings.load().host == "0.0.0.0"

    monkeypatch.setenv("WEBLAUNCHER_DSH_PORT", "5000")
    assert settings.load().port == 5000


def test_explicit_beats_env(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBLAUNCHER_DSH_PORT", "5000")
    assert settings.load(port=6000).port == 6000


def test_no_dedupe_env_disables_focus(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBLAUNCHER_NO_DEDUPE", "1")
    assert settings.load().dedupe is False


def test_single_window_shares_tabbed_profile(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated_home / "config.toml").write_text("[ui]\nsingle_window = true\n", "utf-8")
    loaded = settings.load()
    assert loaded.single_window is True
    assert loaded.profile_dir == isolated_home / "tabbed-browser"
    assert loaded.daily_profile is False

    monkeypatch.setenv("WEBLAUNCHER_SINGLE_WINDOW", "1")
    assert settings.load().single_window is True


def test_single_window_can_use_daily_chrome_profile(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_home / "config.toml").write_text(
        '[ui]\nsingle_window = true\nsingle_window_profile = "daily"\n',
        "utf-8",
    )
    loaded = settings.load()
    assert loaded.single_window is True
    assert loaded.daily_profile is True
    assert loaded.profile_dir == isolated_home / "tabbed-browser"

    monkeypatch.setenv("WEBLAUNCHER_SINGLE_WINDOW_PROFILE", "tabbed")
    assert settings.load().daily_profile is False


def test_daily_profile_is_ignored_without_single_window(isolated_home: Path) -> None:
    (isolated_home / "config.toml").write_text(
        '[ui]\nsingle_window_profile = "daily"\n',
        "utf-8",
    )
    assert settings.load().daily_profile is False


def test_invalid_single_window_profile_is_rejected(isolated_home: Path) -> None:
    (isolated_home / "config.toml").write_text(
        '[ui]\nsingle_window = true\nsingle_window_profile = "unknown"\n',
        "utf-8",
    )
    with pytest.raises(ValueError, match="single_window_profile"):
        settings.load()
