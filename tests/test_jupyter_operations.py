from pathlib import Path

import pytest

from weblauncher.services.jupyter import operations


def test_resolve_python_prefers_project_venv(tmp_path: Path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("", "utf-8")
    assert operations.resolve_python(directory=tmp_path) == python


def test_resolve_python_accepts_explicit_file(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_text("", "utf-8")
    assert operations.resolve_python(directory=python) == python
    assert operations.resolve_python(python=python) == python


def test_resolve_python_reports_missing_venv(tmp_path: Path) -> None:
    with pytest.raises(operations.JupyterOperationError, match="没有找到"):
        operations.resolve_python(directory=tmp_path)


def test_resolve_python_requires_an_argument() -> None:
    with pytest.raises(operations.JupyterOperationError, match="必须给出"):
        operations.resolve_python()


def test_select_workdir_does_not_require_jupyter_install(tmp_path: Path) -> None:
    workdir = tmp_path / "notebooks"
    workdir.mkdir()
    memory: dict = {}
    selected = operations.select_workdir(None, memory, workdir)
    assert selected == workdir.resolve()
    assert memory["jupyter"]["workdir"] == str(workdir.resolve())
