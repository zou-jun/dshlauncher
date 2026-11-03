from pathlib import Path

import pytest

from dshlauncher import paths, settings


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DSHLAUNCHER_HOME", str(tmp_path))
    monkeypatch.delenv("DSHLAUNCHER_OZONE", raising=False)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def test_default_is_auto(isolated_home: Path) -> None:
    assert settings.load().ozone == "auto"


def test_env_beats_file(isolated_home: Path) -> None:
    (isolated_home / "config.toml").write_text('ozone = "x11"\n', "utf-8")
    assert settings.load().ozone == "x11"


def test_explicit_beats_env(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSHLAUNCHER_OZONE", "wayland")
    assert settings.load(ozone="x11").ozone == "x11"


def test_invalid_value_rejected(isolated_home: Path) -> None:
    with pytest.raises(ValueError):
        settings.load(ozone="xwayland")
