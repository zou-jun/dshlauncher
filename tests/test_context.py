"""Context 绑定运行时路径与浏览器 profile。"""

from __future__ import annotations

from pathlib import Path

from weblauncher.paths import Paths
from weblauncher.services.dsh.context import Context
from weblauncher.services.dsh.settings import Settings


def test_context_binds_profile_to_paths(tmp_path: Path) -> None:
    context = Context.create(Settings(), paths_=Paths(tmp_path))
    assert context.paths.data == tmp_path
    assert context.settings.profile_dir == tmp_path / "services" / "dsh" / "browser"
    assert context.service().paths == context.paths


def test_explicit_profile_is_kept(tmp_path: Path) -> None:
    settings = Settings(profile_dir=tmp_path / "custom", profile_explicit=True)
    context = Context.create(settings, paths_=Paths(tmp_path))
    assert context.settings.profile_dir == tmp_path / "custom"
