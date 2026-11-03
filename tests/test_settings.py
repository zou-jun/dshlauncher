import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from dshlauncher import paths, settings


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("DSHLAUNCHER_HOME", str(tmp_path))
    for name in ("PORT", "HOST", "CWD", "BROWSER", "NO_DEDUPE"):
        monkeypatch.delenv("DSHLAUNCHER_" + name, raising=False)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def test_defaults(isolated_home: Path) -> None:
    loaded = settings.load()
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 3080
    assert loaded.work_dir == Path(tempfile.gettempdir())
    assert loaded.dedupe is True


def test_file_beats_default_and_env_beats_file(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated_home / "config.toml").write_text('port = 4000\nhost = "0.0.0.0"\n', "utf-8")
    assert settings.load().port == 4000
    assert settings.load().host == "0.0.0.0"

    monkeypatch.setenv("DSHLAUNCHER_PORT", "5000")
    assert settings.load().port == 5000


def test_explicit_beats_env(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSHLAUNCHER_PORT", "5000")
    assert settings.load(port=6000).port == 6000


def test_no_dedupe_env_disables_focus(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSHLAUNCHER_NO_DEDUPE", "1")
    assert settings.load().dedupe is False
