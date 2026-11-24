import sys
from pathlib import Path

import pytest

from weblauncher.services.dsh import discovery


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NODE", "DSH_BIN"):
        monkeypatch.delenv("WEBLAUNCHER_DSH_" + name, raising=False)
    discovery.reset_cache()
    yield
    discovery.reset_cache()


def _make_dsh(root: Path) -> Path:
    entry = root / "lib" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", "utf-8")
    return entry


@pytest.mark.skipif(sys.platform == "win32", reason="创建 symlink 在 Windows 上需要额外权限")
def test_dsh_shim_symlinked_to_bin_js(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _make_dsh(tmp_path / "local")
    shim = tmp_path / "local" / "bin" / "dsh"
    shim.parent.mkdir(parents=True)
    shim.symlink_to(entry)

    monkeypatch.setattr(discovery.shutil, "which", lambda name: str(shim) if name == "dsh" else None)
    monkeypatch.setattr(discovery, "_node_module_roots", lambda: [])

    assert discovery.dsh_bin() == entry


def test_configured_dsh_skips_probing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """显式配置命中时不能再去跑 npm/pnpm（Windows 上每次约 1 秒）。"""
    entry = _make_dsh(tmp_path / "local")

    def probe(*args: object, **kwargs: object) -> None:
        raise AssertionError("显式配置时不应探测包管理器")

    monkeypatch.setattr(discovery, "_node_module_roots", probe)
    monkeypatch.setattr(discovery.shutil, "which", probe)

    assert discovery.dsh_bin(entry) == entry


def test_dsh_from_npm_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prefix = tmp_path / "prefix"
    entry = _make_dsh(prefix)

    def which(name: str) -> str | None:
        return "/usr/bin/npm" if name == "npm" else None

    def run(args: list[str]) -> str | None:
        return str(prefix) if args[-2:] == ["get", "prefix"] else None

    # 断言的是 POSIX 布局（<prefix>/lib/node_modules），同时屏蔽
    # Windows 的 %APPDATA%\npm 固定候选，避免命中本机真实安装。
    monkeypatch.setattr(discovery, "WINDOWS", False)
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

    monkeypatch.setattr(discovery.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(discovery.shutil, "which", lambda name: None)
    monkeypatch.setattr(discovery, "WINDOWS", False)

    assert node in discovery.node_candidates()


def test_versioned_dirs_sort_numerically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for version in ("v9.0.0", "v20.1.0"):
        (tmp_path / ".nvm" / "versions" / "node" / version).mkdir(parents=True)
    monkeypatch.setattr(discovery.Path, "home", classmethod(lambda cls: tmp_path))
    found = discovery._versioned_dirs(".nvm/versions/node/*")
    assert [path.name for path in found] == ["v20.1.0", "v9.0.0"]
