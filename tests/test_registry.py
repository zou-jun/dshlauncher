from __future__ import annotations

import pytest

from weblauncher.services import registry


def test_ids_and_split() -> None:
    assert registry.ids() == ("dsh", "jupyter")
    assert registry.split("all") == ("dsh", "jupyter")
    assert registry.split("jupyter") == ("jupyter",)
    assert registry.split("dsh,jupyter") == ("dsh", "jupyter")


def test_unknown_service_is_rejected() -> None:
    with pytest.raises(KeyError, match="未知服务"):
        registry.split("wat")


def test_runtime_contexts_skip_unavailable_service(tmp_path, monkeypatch) -> None:  # noqa: ANN001 - pytest 注入
    from weblauncher import paths
    from weblauncher.context import Runtime
    from weblauncher.services import registry

    runtime = Runtime.create(paths_=paths.Paths(tmp_path), migrate=False)
    real_build = registry.build

    def build(runtime_, service_id, *, cli=None):  # noqa: ANN001, ANN202
        if service_id == "jupyter":
            raise RuntimeError("jupyter 未安装")
        return real_build(runtime_, service_id, cli=cli)

    monkeypatch.setattr(registry, "build", build)
    contexts = runtime.contexts()
    assert [context.service_id for context in contexts] == ["dsh"]
    assert "jupyter" in runtime.errors


def test_jupyter_context_does_not_require_executable_for_stop(tmp_path, monkeypatch) -> None:  # noqa: ANN001 - pytest 注入
    from weblauncher import paths
    from weblauncher.context import Runtime
    from weblauncher.services import registry
    from weblauncher.services.jupyter import discovery

    runtime = Runtime.create(paths_=paths.Paths(tmp_path), migrate=False)
    monkeypatch.setattr(
        discovery,
        "find",
        lambda configured=None: (_ for _ in ()).throw(AssertionError("不应探测")),
    )
    context = registry.build(runtime, "jupyter")
    work_dir = context.adapter.work_dir()
    assert work_dir == context.settings.root_dir
    with pytest.raises(AssertionError, match="不应探测"):
        _ = context.adapter.install
