"""控制器动作锁与控制器注册表快照。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from weblauncher import paths
from weblauncher.context import Runtime
from weblauncher.controller import ServiceController, ServiceControllerRegistry


def _controller(tmp_path: Path) -> ServiceController:
    runtime = Runtime.create(paths_=paths.Paths(tmp_path), backend=SimpleNamespace(), migrate=False)
    return ServiceController(runtime.context("dsh"))


def test_controller_try_begin_is_exclusive_and_reusable(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    assert controller.try_begin() is True
    assert controller.try_begin() is False
    assert controller.busy is True
    controller.end()
    assert controller.try_begin() is True
    controller.end()
    assert controller.run_exclusive(lambda: "done") == "done"
    controller.mark_stopping()
    assert controller.stopping is True


def test_registry_snapshot_is_a_copy_and_replace_is_atomic(tmp_path: Path) -> None:
    first = _controller(tmp_path)
    second = _controller(tmp_path)
    registry = ServiceControllerRegistry({"dsh": first}, errors={"jupyter": "bad"})
    snapshot = registry.snapshot()
    snapshot["dsh"] = second
    assert registry.get("dsh") is first
    assert registry.values() == (first,)
    assert registry.ids() == ("dsh",)
    assert registry.errors() == {"jupyter": "bad"}

    registry.replace({"jupyter": second}, errors={"dsh": "broken"})
    assert registry.get("dsh") is None
    assert registry.get("jupyter") is second
    assert registry.values() == (second,)
    assert registry.ids() == ("jupyter",)
    assert registry.errors() == {"dsh": "broken"}
    assert "jupyter" in registry
    assert len(registry) == 1
