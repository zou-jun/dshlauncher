"""uv tool 布局下的 jupyter-lab 发现。"""

from __future__ import annotations

from pathlib import Path

import pytest

from weblauncher.services.jupyter import discovery


def _tool(tmp_path: Path) -> Path:
    tool = tmp_path / "tools" / "jupyterlab"
    scripts = tool / ("Scripts" if discovery.WINDOWS else "bin")
    scripts.mkdir(parents=True)
    lab = scripts / ("jupyter-lab.exe" if discovery.WINDOWS else "jupyter-lab")
    lab.write_text("", "utf-8")
    (tool / "pyvenv.cfg").write_text("", "utf-8")
    (tool / "uv-receipt.toml").write_text(
        f'[tool]\n[[tool.entrypoints]]\nname = "jupyter-lab"\ninstall-path = "{lab.as_posix()}"\n',
        "utf-8",
    )
    return tool


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(discovery.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)
    monkeypatch.setattr(discovery, "uv_tool_root", lambda: tmp_path / "tools")
    discovery.reset_cache()
    yield tmp_path
    discovery.reset_cache()


def test_finds_tool_env_and_derives_jupyter(clean: Path) -> None:
    tool = _tool(clean)
    install = discovery.find()
    assert install.lab == tool / ("Scripts" if discovery.WINDOWS else "bin") / (
        "jupyter-lab.exe" if discovery.WINDOWS else "jupyter-lab"
    )
    assert install.env == tool
    assert install.jupyter is None  # 假环境里没有 jupyter.exe/bin/jupyter


def test_explicit_path_wins(clean: Path) -> None:
    tool = _tool(clean)
    explicit = clean / "custom" / ("jupyter-lab.exe" if discovery.WINDOWS else "jupyter-lab")
    explicit.parent.mkdir()
    explicit.write_text("", "utf-8")
    install = discovery.find(explicit)
    assert install.argv[0] == str(explicit)
    assert install.env is None
    assert tool.exists()


def test_missing_raises(clean: Path) -> None:
    with pytest.raises(discovery.DiscoveryError):
        discovery.find()
