"""升级编排：顺序、停服/重启、失败分支。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from weblauncher.paths import Paths
from weblauncher.services.dsh import updates, upgrade
from weblauncher.services.dsh.settings import Settings


class FakeService:
    def __init__(self, running: bool = True) -> None:
        self.running = running
        self.stopped = 0
        self.started = 0

    def status(self, *, check_ports: bool = True) -> SimpleNamespace:
        return SimpleNamespace(running=self.running)

    def stop(self) -> bool:
        self.stopped += 1
        self.running = False
        return True

    def start(self) -> SimpleNamespace:
        self.started += 1
        self.running = True
        return SimpleNamespace(pid=1)


def _report(*, dsh_update: bool = True, plugin_update: bool = True) -> updates.UpdateReport:
    dsh = updates.DshUpdate(
        "@deepseek-ai/dsh",
        "0.2.2-rc.2",
        "0.2.2-rc.5",
        dsh_update,
        True,
        "npm",
        "npm install -g @deepseek-ai/dsh@0.2.2-rc.5",
    )
    plugin = updates.PluginUpdate(
        "dsh-context",
        "^0.84.0",
        "0.84.0",
        "0.84.1",
        "0.87.1",
        "update" if plugin_update else "current",
        "",
    )
    return updates.UpdateReport(
        "2026-11-23T00:00:00",
        dsh,
        updates.ProfileReport("web", "/tmp/web", 1, (plugin,)),
    )


def _manager(tmp_path: Path, service: FakeService) -> upgrade.UpgradeManager:
    context = SimpleNamespace(
        settings=Settings(),
        paths=Paths(tmp_path),
        service=lambda: service,
    )
    return upgrade.UpgradeManager(context)  # type: ignore[arg-type]


def test_plan_puts_dsh_first(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeService())
    plan = manager._plan(["plugin:dsh-context", "dsh"], _report())
    assert [row[0] for row in plan] == ["dsh", "plugin:dsh-context"]


def test_plan_rejects_unknown_or_current(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeService())
    with pytest.raises(upgrade.UpgradeError, match="未知升级目标"):
        manager._plan(["wat"], _report())
    with pytest.raises(upgrade.UpgradeError, match="已是最新"):
        manager._plan(["plugin:dsh-context"], _report(plugin_update=False))
    with pytest.raises(upgrade.UpgradeError, match="已是最新"):
        manager._plan(["dsh"], _report(dsh_update=False))


def test_execute_stops_once_upgrades_in_order_and_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = FakeService(running=True)
    manager = _manager(tmp_path, service)
    report = _report()
    job = upgrade.UpgradeJob(id="job", started_at="now")
    plan = manager._plan(["plugin:dsh-context", "dsh"], report)
    job.steps = [upgrade.Step(target, label, version) for target, label, version in plan]

    order: list[str] = []
    monkeypatch.setattr(
        manager,
        "_upgrade_dsh",
        lambda job, version, report: order.append("dsh") or "ok",
    )
    monkeypatch.setattr(
        manager,
        "_upgrade_plugin",
        lambda job, name, version, report: order.append(name) or "ok",
    )

    manager._execute(job, plan, report)

    assert order == ["dsh", "dsh-context"]
    assert service.stopped == 1
    assert service.started == 1
    assert job.status == "succeeded"
    assert all(step.status == "ok" for step in job.steps)


def test_dsh_failure_skips_plugins_and_restarts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeService(running=True)
    manager = _manager(tmp_path, service)
    report = _report()
    job = upgrade.UpgradeJob(id="job", started_at="now")
    plan = manager._plan(["dsh", "plugin:dsh-context"], report)
    job.steps = [upgrade.Step(target, label, version) for target, label, version in plan]

    def fail(*args: object) -> str:
        raise upgrade.UpgradeError("boom")

    monkeypatch.setattr(manager, "_upgrade_dsh", fail)
    monkeypatch.setattr(manager, "_upgrade_plugin", lambda *args: "unexpected")

    manager._execute(job, plan, report)

    assert job.status == "failed"
    assert job.steps[0].status == "failed"
    assert job.steps[1].status == "skipped"
    assert service.started == 1


def test_plugin_failure_marks_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = FakeService(running=True)
    manager = _manager(tmp_path, service)
    report = _report()
    job = upgrade.UpgradeJob(id="job", started_at="now")
    plan = manager._plan(["dsh", "plugin:dsh-context"], report)
    job.steps = [upgrade.Step(target, label, version) for target, label, version in plan]

    monkeypatch.setattr(manager, "_upgrade_dsh", lambda *args: "ok")

    def fail(*args: object) -> str:
        raise upgrade.UpgradeError("bad plugin")

    monkeypatch.setattr(manager, "_upgrade_plugin", fail)

    manager._execute(job, plan, report)

    assert job.status == "partial"
    assert [step.status for step in job.steps] == ["ok", "failed"]


def test_start_rejects_running_job(tmp_path: Path) -> None:
    manager = _manager(tmp_path, FakeService())
    running = upgrade.UpgradeJob(id="job", status="running", started_at="now")
    manager._job = running
    with pytest.raises(upgrade.BusyError):
        manager.start(["dsh"], _report())


def test_dsh_command_uses_detected_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path, FakeService())
    report = _report()
    job = upgrade.UpgradeJob(id="job", started_at="now")
    commands: list[list[str]] = []
    monkeypatch.setattr(upgrade.shutil, "which", lambda name: "npm.exe" if name == "npm" else None)
    monkeypatch.setattr(manager, "_run_streaming", lambda job, command, cwd: commands.append(command))
    monkeypatch.setattr(upgrade.discovery, "reset_cache", lambda: None)
    monkeypatch.setattr(upgrade.updates, "installed_dsh_version", lambda settings: "0.2.2-rc.5")

    assert manager._upgrade_dsh(job, "0.2.2-rc.5", report) == "已升级到 0.2.2-rc.5"
    assert commands == [["npm.exe", "install", "-g", "@deepseek-ai/dsh@0.2.2-rc.5"]]


def test_plugin_command_uses_dsh_plugin_add(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path, FakeService())
    report = _report()
    job = upgrade.UpgradeJob(id="job", started_at="now")
    commands: list[list[str]] = []
    monkeypatch.setattr(upgrade.discovery, "node_exe", lambda configured: Path("node"))
    monkeypatch.setattr(upgrade.discovery, "dsh_bin", lambda configured: Path("bin.js"))
    monkeypatch.setattr(manager, "_run_streaming", lambda job, command, cwd: commands.append(command))
    monkeypatch.setattr(upgrade.updates, "installed_plugin_version", lambda directory, name: "0.87.1")

    assert manager._upgrade_plugin(job, "dsh-context", "0.87.1", report) == "已升级到 0.87.1"
    assert commands[0][2:] == [
        "plugin",
        "--profile",
        "web",
        "add",
        "dsh-context@0.87.1",
        "--save-exact",
    ]


def test_streaming_command_records_output(tmp_path: Path) -> None:
    import sys

    manager = _manager(tmp_path, FakeService())
    job = upgrade.UpgradeJob(id="job", started_at="now")
    manager._run_streaming(
        job,
        [sys.executable, "-c", "print('first'); print('second')"],
        cwd=tmp_path,
    )
    assert any("first" in line for line in job.log)
    assert any("second" in line for line in job.log)


def test_log_keeps_tail_and_persists_full_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(upgrade, "LOG_LIMIT", 3)
    manager = _manager(tmp_path, FakeService())
    job = upgrade.UpgradeJob(id="job", started_at="now")
    for index in range(5):
        manager._log(job, f"line {index}")

    assert job.log[-1].endswith("line 4")
    assert len(job.log) == 3
    persisted = (tmp_path / "upgrades.log").read_text("utf-8")
    assert "line 0" in persisted and "line 4" in persisted
