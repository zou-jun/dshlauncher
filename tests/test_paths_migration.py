"""单服务数据布局到 services/<id>/ 的一次性迁移。"""

from __future__ import annotations

from pathlib import Path

from weblauncher import paths


def test_migration_moves_state_log_and_profile(tmp_path: Path) -> None:
    tmp_path.joinpath("state.json").write_text('{"pid": 1}', "utf-8")
    tmp_path.joinpath("dsh-web.log").write_text("old log", "utf-8")
    tmp_path.joinpath("browser").mkdir()
    tmp_path.joinpath("browser", "x").write_text("", "utf-8")

    bundle = paths.Paths(tmp_path)
    moved = bundle.migrate_legacy()
    assert any(item.startswith("state.json") for item in moved)
    assert bundle.service("dsh").state.is_file()
    assert bundle.service("dsh").log.read_text("utf-8") == "old log"
    assert (bundle.service("dsh").profile / "x").is_file()
    assert not tmp_path.joinpath("dsh-web.log").exists()


def test_migration_is_idempotent_and_keeps_newer_files(tmp_path: Path) -> None:
    service = paths.Paths(tmp_path).service("dsh")
    service.ensure()
    service.state.write_text('{"pid": 2}', "utf-8")
    tmp_path.joinpath("state.json").write_text('{"pid": 1}', "utf-8")
    assert paths.Paths(tmp_path).migrate_legacy() == []
    assert service.state.read_text("utf-8") == '{"pid": 2}'
