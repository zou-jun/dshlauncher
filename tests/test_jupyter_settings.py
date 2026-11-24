"""Jupyter 配置优先级、工作目录与内核记忆。"""

from __future__ import annotations

from pathlib import Path

import pytest

from weblauncher import config, paths
from weblauncher.services.jupyter import settings


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("WEBLAUNCHER_HOME", str(tmp_path))
    for name in ("HOST", "PORT", "ROOT", "KERNEL", "BASE_URL"):
        monkeypatch.delenv("WEBLAUNCHER_JUPYTER_" + name, raising=False)
    paths.data_dir.cache_clear()
    yield tmp_path
    paths.data_dir.cache_clear()


def test_defaults(isolated: Path) -> None:
    loaded = settings.load()
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8888
    assert loaded.base_url == "/"
    assert loaded.root_dir == Path.home()
    assert loaded.start_timeout == 60.0


def test_config_env_and_cli_precedence(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated / "config.toml").write_text(
        '[jupyter]\nport = 8890\nroot_dir = "E:/from-config"\n',
        "utf-8",
    )
    cfg = config.load()
    assert settings.load(config=cfg).port == 8890
    monkeypatch.setenv("WEBLAUNCHER_JUPYTER_PORT", "8891")
    assert settings.load(config=cfg).port == 8891
    assert settings.load(config=cfg, port=8892).port == 8892
    assert settings.load(config=cfg, root="E:/cli").root_dir == Path("E:/cli")


def test_workdir_kernel_memory(isolated: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "notebooks"
    workdir.mkdir()
    mem = {
        "jupyter": {
            "workdir": str(workdir),
            "kernel": "global",
            "workdir_kernels": {str(workdir): "local"},
        }
    }
    loaded = settings.load(memory=mem)
    assert loaded.root_dir == workdir
    assert loaded.kernel == "local"


def test_remember_per_workdir_can_be_disabled(isolated: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "notebooks"
    workdir.mkdir()
    mem = {
        "jupyter": {
            "workdir": str(workdir),
            "kernel": "global",
            "workdir_kernels": {str(workdir): "local"},
        }
    }
    loaded = settings.load(memory=mem, config=config.load())
    assert loaded.kernel == "local"
    (isolated / "config.toml").write_text("[jupyter]\nremember_per_workdir = false\n", "utf-8")
    loaded = settings.load(memory=mem, config=config.load())
    assert loaded.kernel == "global"


def test_base_url_is_normalized(isolated: Path) -> None:
    assert settings.load(base_url="lab").base_url == "/lab/"
    assert settings.load(base_url="/lab/").base_url == "/lab/"
    assert settings.load(base_url="/").base_url == "/"


def test_fixed_token_from_env(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBLAUNCHER_JUPYTER_TOKEN", "fixed")
    assert settings.load().token == "fixed"
