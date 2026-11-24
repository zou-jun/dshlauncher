"""控制台 Jupyter 领域服务：内存保存、reload 与错误转换。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from weblauncher.context import Runtime
from weblauncher.control import jupyter as control_jupyter
from weblauncher.control.errors import ControlError
from weblauncher.control.jupyter import JupyterService
from weblauncher.services.jupyter import kernels as jupyter_kernels
from weblauncher.services.jupyter import operations as jupyter_operations


class _Kernel:
    name = "demo"

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "display_name": "Demo"}


def _service(tmp_path: Path, *, reload=None):
    context = SimpleNamespace(
        adapter=SimpleNamespace(install=object()),
        settings=SimpleNamespace(root_dir=tmp_path, kernel="demo"),
    )
    runtime = SimpleNamespace(
        memory={},
        paths=SimpleNamespace(memory=tmp_path / "memory.toml"),
        context=lambda service_id: context,
    )
    return JupyterService(cast(Runtime, runtime), reload=reload or (lambda: None)), runtime, context


def test_add_kernel_saves_memory_and_reloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reloads: list[int] = []
    saved: list[Path | None] = []
    calls: list[dict] = []
    service, runtime, _ = _service(tmp_path, reload=lambda: reloads.append(1))
    monkeypatch.setattr(control_jupyter.memory, "save", lambda data, path=None: saved.append(path))
    monkeypatch.setattr(
        jupyter_operations,
        "add_kernel",
        lambda *args, **kwargs: calls.append(kwargs) or _Kernel(),
    )
    result = service.add_kernel({"dir": str(tmp_path), "python": "python.exe"})
    assert result == {"name": "demo", "display_name": "Demo"}
    assert calls[0]["directory"] == str(tmp_path)
    assert calls[0]["python"] == "python.exe"
    assert saved == [runtime.paths.memory]
    assert reloads == [1]


def test_use_and_remove_kernel_reload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reloads: list[int] = []
    service, _, _ = _service(tmp_path, reload=lambda: reloads.append(1))
    monkeypatch.setattr(control_jupyter.memory, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(jupyter_operations, "select_kernel", lambda *args, **kwargs: _Kernel())
    monkeypatch.setattr(jupyter_operations, "remove_kernel", lambda *args, **kwargs: _Kernel())
    assert service.use_kernel("demo") == {"kernel": "demo", "restart_required": True}
    assert service.remove_kernel("demo", force=True) == {"removed": "demo"}
    assert reloads == [1, 1]


def test_operation_errors_become_control_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)

    def fail(*args, **kwargs):
        raise jupyter_operations.JupyterOperationError("bad kernel")

    monkeypatch.setattr(jupyter_operations, "add_kernel", fail)
    with pytest.raises(ControlError, match="bad kernel"):
        service.add_kernel({})
    monkeypatch.setattr(
        jupyter_operations,
        "select_kernel",
        lambda *args, **kwargs: (_ for _ in ()).throw(jupyter_kernels.KernelError("missing")),
    )
    with pytest.raises(ControlError, match="missing"):
        service.use_kernel("missing")


def test_use_workdir_without_kernel_does_not_require_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    service, _, _ = _service(tmp_path)
    seen: list[object] = []
    monkeypatch.setattr(control_jupyter.memory, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        jupyter_operations,
        "select_workdir",
        lambda install, memory, value, **kwargs: seen.append(install) or tmp_path,
    )
    assert service.use_workdir(str(tmp_path)) == {"path": str(tmp_path), "restart_required": True}
    assert seen == [None]


def test_workdirs_and_context_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service, runtime, _ = _service(tmp_path)
    runtime.memory = {"jupyter": {"workdir": str(tmp_path), "recent_workdirs": [str(tmp_path)]}}
    monkeypatch.setattr(
        control_jupyter.jupyter_workdirs,
        "recent",
        lambda memory: [tmp_path],
    )
    data = service.workdirs()
    assert data["current"] == str(tmp_path)
    assert data["items"] == [{"path": str(tmp_path), "exists": True, "current": True}]

    runtime.context = lambda service_id: (_ for _ in ()).throw(RuntimeError("no jupyter"))
    with pytest.raises(ControlError, match="Jupyter 不可用"):
        service.kernels()
