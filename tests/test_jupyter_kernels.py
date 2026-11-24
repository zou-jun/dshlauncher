"""kernelspec 列表、注册、改名与删除。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from weblauncher.services.jupyter import kernels
from weblauncher.services.jupyter.discovery import Install


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "jdata"
    target.mkdir()
    monkeypatch.setenv("JUPYTER_DATA_DIR", str(target))
    return target


def _install(tmp_path: Path) -> Install:
    return Install((sys.executable,), tmp_path / "env", None, None)


def _write_kernel(base: Path, name: str, python: str = "python", display: str | None = None) -> Path:
    directory = base / "kernels" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "kernel.json").write_text(
        json.dumps(
            {
                "argv": [python, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                "display_name": display or name,
                "language": "python",
            }
        ),
        "utf-8",
    )
    return directory


def test_list_merges_env_before_user(tmp_path: Path, data_dir: Path) -> None:
    _write_kernel(data_dir, "shared", "E:/user/python.exe", "User")
    _write_kernel(tmp_path / "env" / "share" / "jupyter", "shared", "E:/env/python.exe", "Env")
    _write_kernel(tmp_path / "env" / "share" / "jupyter", "python3", "python", "Python 3")
    specs = kernels.list_kernels(_install(tmp_path), {})
    assert [spec.name for spec in specs] == ["python3", "shared"]
    assert next(spec for spec in specs if spec.name == "shared").display_name == "Env"


def test_add_kernel_builds_ipykernel_install_command(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(kernels, "validate_interpreter", lambda python: "")

    def fake_run(args: list[str], *, timeout: float = 120.0) -> tuple[int, str]:
        calls.append(args)
        name = args[args.index("--name") + 1]
        display = args[args.index("--display-name") + 1]
        _write_kernel(data_dir, name, "E:/project/.venv/python.exe", display)
        return 0, "installed"

    monkeypatch.setattr(kernels, "_run", fake_run)
    spec = kernels.add_kernel(
        _install(tmp_path),
        {},
        Path("E:/project/.venv/python.exe"),
        name="proj",
        display_name="项目",
    )
    assert spec.name == "proj"
    assert spec.display_name == "项目"
    assert calls[0][1:6] == ["-m", "ipykernel", "install", "--user", "--name"]


def test_add_refuses_existing_unless_replace(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_kernel(data_dir, "proj", "E:/a/python.exe")
    monkeypatch.setattr(kernels, "validate_interpreter", lambda python: "")
    with pytest.raises(kernels.KernelError, match="已存在"):
        kernels.add_kernel(_install(tmp_path), {}, Path("E:/b/python.exe"), name="proj")

    def replace_run(args: list[str], *, timeout: float = 120.0) -> tuple[int, str]:
        _write_kernel(data_dir, "proj", "E:/b/python.exe", "Replaced")
        return 0, "ok"

    monkeypatch.setattr(kernels, "_run", replace_run)
    spec = kernels.add_kernel(_install(tmp_path), {}, Path("E:/b/python.exe"), name="proj", replace=True)
    assert spec.display_name == "Replaced"


def test_rename_and_remove_user_kernel(tmp_path: Path, data_dir: Path) -> None:
    _write_kernel(data_dir, "proj", "E:/a/python.exe", "Old")
    spec = kernels.require_found(_install(tmp_path), {}, "proj")
    renamed = kernels.rename_kernel(spec, "新名字")
    assert renamed.display_name == "新名字"
    assert json.loads((spec.resource_dir / "kernel.json").read_text("utf-8"))["display_name"] == "新名字"
    kernels.remove_kernel(renamed)
    assert not spec.resource_dir.exists()


def test_system_kernel_cannot_be_modified(tmp_path: Path, data_dir: Path) -> None:
    env_kernels = tmp_path / "env" / "share" / "jupyter"
    system = _write_kernel(env_kernels, "python3", "python", "Python 3")
    spec = next(item for item in kernels.list_kernels(_install(tmp_path), {}) if item.name == "python3")
    with pytest.raises(kernels.KernelError, match="不是用户内核"):
        kernels.remove_kernel(spec)
    assert system.exists()


def test_default_name_from_project_venv() -> None:
    assert kernels.default_name(Path("E:/develop_self/FinMate/.venv/Scripts/python.exe")) == "finmate"
    assert kernels.default_name(Path("E:/a/b/python.exe")) == "b"


def test_validate_name() -> None:
    assert kernels.NAME_RE.match("proj-1")
    assert not kernels.NAME_RE.match("Proj With Space")
