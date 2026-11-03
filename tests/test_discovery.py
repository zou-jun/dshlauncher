from pathlib import Path

import pytest

from dshlauncher import discovery


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NODE", "DSH_BIN"):
        monkeypatch.delenv("DSHLAUNCHER_" + name, raising=False)


def _make_dsh(root: Path) -> Path:
    entry = root / "lib" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", "utf-8")
    return entry


def test_dsh_shim_symlinked_to_bin_js(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_dsh(tmp_path / "local")
    shim = tmp_path / "local" / "bin" / "dsh"
    shim.parent.mkdir(parents=True)
    shim.symlink_to(entry)

    monkeypatch.setattr(discovery.shutil, "which", lambda name: str(shim) if name == "dsh" else None)
    monkeypatch.setattr(discovery, "_node_module_roots", lambda: [])

    assert discovery.dsh_bin() == entry


def test_dsh_from_npm_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = tmp_path / "prefix"
    entry = _make_dsh(prefix)

    def which(name: str) -> str | None:
        return "/usr/bin/npm" if name == "npm" else None

    def run(args: list[str]) -> str | None:
        return str(prefix) if args[-2:] == ["get", "prefix"] else None

    monkeypatch.setattr(discovery.shutil, "which", which)
    monkeypatch.setattr(discovery, "_run_command", run)

    assert discovery.dsh_bin() == entry


def test_dsh_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)
    monkeypatch.setattr(discovery, "_node_module_roots", lambda: [])
    with pytest.raises(discovery.DiscoveryError):
        discovery.dsh_bin()


def test_node_candidates_include_nvm_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    node = tmp_path / ".nvm" / "versions" / "node" / "v20.0.0" / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text("", "utf-8")

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)
    monkeypatch.setattr(discovery, "WINDOWS", False)

    assert node in discovery.node_candidates()
