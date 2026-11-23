"""更新检查：semver、profile 解析、聚合与文本输出。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dshlauncher import updates
from dshlauncher.settings import Settings


def test_semver_orders_prereleases_numerically() -> None:
    assert updates.compare_versions("0.2.2-rc.5", "0.2.2-rc.2") == 1
    assert updates.compare_versions("0.2.2", "0.2.2-rc.5") == 1
    assert updates.compare_versions("0.2.10", "0.2.9") == 1
    assert updates.compare_versions("v1.0.0+build", "1.0.0") == 0
    assert updates.compare_versions("0.2.2-rc.10", "0.2.2-rc.9") == 1


def test_semver_rejects_invalid() -> None:
    assert updates.compare_versions("next", "1.0.0") is None
    assert updates.is_newer("0.0.0.1", "0.0.0") is False


@pytest.mark.parametrize(
    ("spec", "kind"),
    [
        ("^1.2.3", "registry"),
        ("1.2.3", "registry"),
        ("latest", "registry"),
        ("file:../local", "local"),
        ("link:../local", "local"),
        ("workspace:*", "local"),
        ("git+https://example.com/a.git", "remote"),
        ("github:user/repo", "remote"),
        ("user/repo", "remote"),
        ("npm:dsh-pet@0.4.8", "alias"),
        ("@scope/pkg", "registry"),
    ],
)
def test_spec_kind(spec: str, kind: str) -> None:
    assert updates.spec_kind(spec) == kind


def test_parse_outdated_normalizes_and_skips_non_objects() -> None:
    payload = {
        "a": {"current": "1.0.0", "wanted": "1.1.0", "latest": "2.0.0", "extra": [1]},
        "bad": "nope",
    }
    assert updates.parse_outdated(payload) == {
        "a": {"current": "1.0.0", "wanted": "1.1.0", "latest": "2.0.0"}
    }
    assert updates.parse_outdated([]) == {}


def _write_profile(home: Path, manifest: dict) -> Path:
    directory = home / "profiles" / "web"
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(json.dumps(manifest), "utf-8")
    return directory


def _write_installed(directory: Path, name: str, version: str) -> None:
    target = directory / "node_modules" / Path(name)
    target.mkdir(parents=True)
    (target / "package.json").write_text(json.dumps({"name": name, "version": version}), "utf-8")


def test_profile_report_classifies_updates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "dsh"
    directory = _write_profile(
        home,
        {
            "dependencies": {
                "range": "^1.0.0",
                "pinned": "2.0.0",
                "blocked": "~3.0.0",
                "local": "file:../local",
                "alias": "npm:@scope/pkg@1.0.0",
                "fresh": "^4.0.0",
            }
        },
    )
    _write_installed(directory, "range", "1.0.0")
    _write_installed(directory, "pinned", "2.0.0")
    _write_installed(directory, "blocked", "3.0.0")
    _write_installed(directory, "alias", "1.0.0")
    _write_installed(directory, "fresh", "4.2.0")
    monkeypatch.setenv("DSH_HOME", str(home))
    monkeypatch.setattr(
        updates,
        "_outdated_entries",
        lambda settings, profile, directory, timeout: (
            {
                "range": {
                    "current": "1.0.0",
                    "wanted": "1.5.0",
                    "latest": "2.0.0",
                },
                "pinned": {
                    "current": "2.0.0",
                    "wanted": "2.0.0",
                    "latest": "2.1.0",
                },
                "blocked": {
                    "current": "3.0.0",
                    "wanted": "3.0.0",
                    "latest": "3.1.0",
                },
            },
            None,
        ),
    )

    report = updates._profile_report(Settings(), "web", 10)

    assert report.total == 6
    states = {plugin.name: plugin.state for plugin in report.plugins}
    assert states["range"] == "update"
    assert states["pinned"] == "pinned"
    assert states["blocked"] == "update"
    assert states["local"] == "unsupported"
    assert states["alias"] == "unsupported"
    assert states["fresh"] == "current"
    assert len(report.updates) == 3


def test_profile_missing_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    report = updates._profile_report(Settings(), "web", 10)
    assert report.error is not None
    assert "未初始化" in report.error


def test_dsh_update_uses_managed_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "node_modules" / "@deepseek-ai" / "dsh"
    (root / "lib").mkdir(parents=True)
    (root / "package.json").write_text(
        json.dumps({"name": "@deepseek-ai/dsh", "version": "0.2.2-rc.2"}), "utf-8"
    )
    monkeypatch.setattr(
        updates,
        "installed_dsh_package",
        lambda settings: (root, {"name": "@deepseek-ai/dsh", "version": "0.2.2-rc.2"}),
    )
    monkeypatch.setattr(
        updates,
        "_latest_version",
        lambda name, cwd, timeout: ("0.2.2-rc.5", "npm", None),
    )
    monkeypatch.setattr(updates, "_global_manager", lambda *args, **kwargs: "npm")

    result = updates._dsh_update(Settings(), 10)

    assert result.update_available is True
    assert result.upgrade_supported is True
    assert result.manager == "npm"
    assert "@0.2.2-rc.5" in result.install


def test_check_aggregates_and_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    dsh = updates.DshUpdate(
        "@deepseek-ai/dsh",
        "0.2.2-rc.2",
        "0.2.2-rc.5",
        True,
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
        "update",
        "现有范围可升到 0.84.1；最新版本需改范围",
    )
    profile_report = updates.ProfileReport("web", "/tmp/web", 1, (plugin,))
    monkeypatch.setattr(updates, "_dsh_update", lambda settings, timeout: dsh)
    monkeypatch.setattr(updates, "_profile_report", lambda settings, name, timeout: profile_report)

    report = updates.check(Settings())

    assert report.update_count == 2
    text = updates.format_report(report)
    assert "0.2.2-rc.2 → 0.2.2-rc.5" in text
    assert "dsh-context" in text
    assert report.as_dict()["profile"]["update_count"] == 1
