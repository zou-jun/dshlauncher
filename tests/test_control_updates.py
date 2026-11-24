"""控制台更新领域服务：缓存、刷新、升级错误与 Job 快照。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from weblauncher.context import Runtime
from weblauncher.control import updates as control_updates
from weblauncher.control.errors import ControlError
from weblauncher.control.updates import UpdatesService
from weblauncher.services.dsh.upgrade import BusyError, UpgradeError


class _Report:
    def __init__(self, value: str = "report") -> None:
        self.value = value

    def as_dict(self) -> dict[str, str]:
        return {"checked_at": self.value}


def _service(monkeypatch: pytest.MonkeyPatch):
    context = SimpleNamespace(settings=object())
    runtime = SimpleNamespace(context=lambda service_id: context)
    return UpdatesService(cast(Runtime, runtime), exclusive_dsh=lambda work: work())


def test_report_cache_refresh_reset_and_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(monkeypatch)
    calls: list[dict] = []

    def check(settings, **kwargs):
        calls.append(kwargs)
        return _Report(kwargs["profile"])

    monkeypatch.setattr(control_updates.dsh_updates, "check", check)
    assert service.report() == {"checked_at": "web"}
    assert service.report() == {"checked_at": "web"}
    assert len(calls) == 1
    assert service.report(refresh=True) == {"checked_at": "web"}
    assert len(calls) == 2
    assert service.report(profile="other") == {"checked_at": "other"}
    assert len(calls) == 3
    service.reset()
    assert service.report() == {"checked_at": "web"}
    assert len(calls) == 4


def test_upgrade_starts_manager_and_returns_job(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(monkeypatch)
    started: list[tuple] = []
    monkeypatch.setattr(control_updates.dsh_updates, "check", lambda *args, **kwargs: _Report())

    class Manager:
        def __init__(self, *args, **kwargs) -> None:
            self.job = SimpleNamespace(as_dict=lambda: {"status": "running"})

        def start(self, targets, report):
            started.append((targets, report))
            return {"status": "running"}

    monkeypatch.setattr(control_updates, "UpgradeManager", Manager)
    assert service.upgrade(["dsh"]) == {"status": "running"}
    assert started[0][0] == ["dsh"]
    assert service.job() == {"status": "running"}


def test_upgrade_errors_map_to_control_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(monkeypatch)
    monkeypatch.setattr(control_updates.dsh_updates, "check", lambda *args, **kwargs: _Report())

    class BusyManager:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def start(self, targets, report):
            raise BusyError("busy")

    monkeypatch.setattr(control_updates, "UpgradeManager", BusyManager)
    with pytest.raises(ControlError) as caught:
        service.upgrade(["dsh"])
    assert caught.value.status == 409

    service.reset()

    class FailedManager(BusyManager):
        def start(self, targets, report):
            raise UpgradeError("failed")

    monkeypatch.setattr(control_updates, "UpgradeManager", FailedManager)
    with pytest.raises(ControlError) as caught:
        service.upgrade(["dsh"])
    assert caught.value.status == 400

    with pytest.raises(ControlError, match="targets"):
        service.upgrade([])
