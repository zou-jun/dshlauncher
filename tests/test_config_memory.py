"""config.toml 的原地编辑与 memory.toml 的原子读写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from weblauncher import config, memory


def test_set_value_preserves_comments_and_section_order(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "# 顶部注释\n[launcher]\nstart_timeout = 120  # 手写\n\n[dsh]\nport = 3080\n",
        "utf-8",
    )
    config.set_value(path, "dsh.port", 4080)
    text = path.read_text("utf-8")
    assert "# 顶部注释" in text
    assert "start_timeout = 120  # 手写" in text
    assert "port = 4080" in text
    assert config.get_value(path, "dsh.port") == 4080


def test_set_value_appends_missing_section(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[launcher]\nstart_timeout = 120\n", "utf-8")
    config.set_value(path, "jupyter.root_dir", "E:/notebooks")
    assert config.get_value(path, "jupyter.root_dir") == "E:/notebooks"


def test_unset_value_removes_only_the_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[dsh]\n# 保留我\nport = 3080\nhost = "127.0.0.1"\n', "utf-8")
    assert config.unset_value(path, "dsh.port") is True
    text = path.read_text("utf-8")
    assert "# 保留我" in text
    assert "port = 3080" not in text
    assert "host" in text


def test_parse_value() -> None:
    assert config.parse_value("true") is True
    assert config.parse_value("18080") == 18080
    assert config.parse_value("1.5") == 1.5
    assert config.parse_value('"C:/x"') == "C:/x"


def test_memory_roundtrip_and_none_clears(tmp_path: Path) -> None:
    path = tmp_path / "memory.toml"
    data = {
        "jupyter": {
            "workdir": "E:/notebooks",
            "recent_workdirs": ["E:/notebooks", "E:/other"],
            "kernel": "project",
            "workdir_kernels": {"E:/notebooks": "project"},
        }
    }
    memory.save(data, path)
    loaded = memory.load(path)
    assert loaded["jupyter"]["workdir"] == "E:/notebooks"
    assert loaded["jupyter"]["recent_workdirs"] == ["E:/notebooks", "E:/other"]
    assert loaded["jupyter"]["workdir_kernels"] == {"E:/notebooks": "project"}

    memory.set_value(loaded, "jupyter", "kernel", None)
    memory.save(loaded, path)
    assert "kernel" not in memory.section(memory.load(path), "jupyter")


def test_memory_corrupt_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "memory.toml"
    path.write_text("not [valid", "utf-8")
    assert memory.load(path) == {}


def test_config_list_prints_raw_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from weblauncher import paths
    from weblauncher.__main__ import main

    monkeypatch.setenv("WEBLAUNCHER_HOME", str(tmp_path))
    paths.data_dir.cache_clear()
    (tmp_path / "config.toml").write_text("[[x]]\na = 1\n", "utf-8")
    try:
        assert main(["config", "list"]) == 0
    finally:
        paths.data_dir.cache_clear()
    assert "[[x]]" in capsys.readouterr().out
