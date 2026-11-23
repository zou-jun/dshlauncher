"""检查 dsh 与 profile 插件的可用更新。

只复用 dsh 自己的运行环境：dsh 装在哪个全局 node_modules 就用哪个包管理器，
profile 插件则在 profile 目录里问 npm / pnpm。这样代理、私有 registry、
认证配置都与 dsh 插件页保持一致，启动器不自己维护 registry 客户端。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import discovery, paths
from .settings import Settings

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0
DEFAULT_TIMEOUT = 30.0
DSH_PACKAGE = "@deepseek-ai/dsh"
VERSION_RE = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")
PINNED_RE = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
SHORTHAND_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:#.*)?$")


# ── semver ────────────────────────────────────────────────────────────
def _pre_key(prerelease: str | None) -> tuple[Any, ...]:
    """SemVer 预发布比较键：数字段 < 字母段，字段少的小于字段多的。"""
    if prerelease is None:
        return (1,)
    parts: list[tuple[int, Any]] = []
    for part in prerelease.split("."):
        parts.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    return (0, tuple(parts))


def parse_version(value: str) -> tuple[int, int, int, tuple[Any, ...]] | None:
    match = VERSION_RE.match((value or "").strip())
    if match is None:
        return None
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        _pre_key(match.group(4)),
    )


def compare_versions(left: str, right: str) -> int | None:
    """返回 -1 / 0 / 1；任一侧不是合法 semver 时返回 None。"""
    parsed_left = parse_version(left)
    parsed_right = parse_version(right)
    if parsed_left is None or parsed_right is None:
        return None
    if parsed_left < parsed_right:
        return -1
    if parsed_left > parsed_right:
        return 1
    return 0


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) == 1


# ── 外部命令 ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> CommandResult:
    """跑一次探测命令；超时或无法启动都转成结果对象。"""
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            env=paths.child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            124,
            _text(exc.stdout),
            _text(exc.stderr),
            timed_out=True,
        )
    except OSError as exc:
        return CommandResult(127, "", f"{type(exc).__name__}: {exc}")
    return CommandResult(result.returncode, result.stdout or "", result.stderr or "")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _tail(text: str, limit: int = 500) -> str:
    cleaned = " / ".join(line.strip() for line in (text or "").splitlines() if line.strip())
    return cleaned[-limit:]


def _load_json(text: str) -> Any:
    """容忍包管理器在 JSON 前后打印提示行。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


# ── profile / dsh 路径 ────────────────────────────────────────────────
def dsh_home() -> Path:
    configured = os.environ.get("DSH_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".dsh"


def profile_dir(name: str) -> Path:
    if not name or name in {".", "..", "node_modules"} or "/" in name or "\\" in name:
        raise ValueError(f"非法 profile 名称：{name!r}")
    return dsh_home() / "profiles" / name


def _find_package(bin_js: Path) -> tuple[Path, dict[str, Any]]:
    """从 bin.js 向上找包根；bin.js 通常位于 <package>/lib/bin.js。"""
    candidate = bin_js.resolve()
    for parent in (candidate.parent, candidate.parent.parent, candidate.parent.parent.parent):
        manifest = parent / "package.json"
        try:
            data = json.loads(manifest.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("name") and data.get("version"):
            return parent, data
    raise RuntimeError(f"找不到 dsh 的 package.json：{bin_js}")


def installed_dsh_package(settings: Settings) -> tuple[Path, dict[str, Any]]:
    return _find_package(discovery.dsh_bin(settings.dsh_bin))


def installed_dsh_version(settings: Settings) -> str:
    _, data = installed_dsh_package(settings)
    return str(data.get("version") or "")


def installed_plugin_version(profile: Path, name: str) -> str:
    manifest = profile / "node_modules" / Path(name) / "package.json"
    try:
        data = json.loads(manifest.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("version") or "") if isinstance(data, dict) else ""


# ── registry 查询 ─────────────────────────────────────────────────────
def _package_manager_roots(timeout: float) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for manager in ("npm", "pnpm"):
        exe = shutil.which(manager)
        if exe is None:
            continue
        result = run_command([exe, "root", "-g"], timeout=timeout)
        if not result.ok:
            continue
        for line in reversed(result.stdout.splitlines()):
            line = line.strip()
            if line:
                roots[manager] = Path(line)
                break
    return roots


def _in_root(path: Path, root: Path) -> bool:
    try:
        left = os.path.normcase(str(path.resolve()))
        right = os.path.normcase(str(root.resolve()))
        return os.path.commonpath([left, right]) == right
    except (OSError, ValueError):
        return False


def _global_manager(
    package_root: Path,
    *,
    explicit: bool,
    timeout: float,
) -> str | None:
    if explicit:
        return None
    for manager, root in _package_manager_roots(timeout).items():
        if _in_root(package_root, root):
            return manager
    return None


def _latest_version(
    name: str,
    *,
    cwd: Path | None,
    timeout: float,
) -> tuple[str, str, str | None]:
    """返回 (latest, manager, error)。先 npm 后 pnpm。"""
    errors: list[str] = []
    for manager in ("npm", "pnpm"):
        exe = shutil.which(manager)
        if exe is None:
            continue
        result = run_command([exe, "view", name, "dist-tags", "--json"], cwd=cwd, timeout=timeout)
        payload = _load_json(result.stdout)
        if result.ok and isinstance(payload, dict):
            latest = str(payload.get("latest") or "").strip()
            if latest:
                return latest, manager, None
        errors.append(f"{manager}: {_tail(result.stderr or result.stdout) or f'exit {result.returncode}'}")
    return "", "", "；".join(errors) or "找不到 npm / pnpm，无法查询 registry"


# ── 数据模型 ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DshUpdate:
    name: str
    current: str
    latest: str
    update_available: bool
    upgrade_supported: bool
    manager: str | None
    install: str
    detail: str = ""
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current": self.current,
            "latest": self.latest,
            "update_available": self.update_available,
            "upgrade_supported": self.upgrade_supported,
            "manager": self.manager,
            "install": self.install,
            "detail": self.detail,
            "error": self.error,
        }


@dataclass(frozen=True)
class PluginUpdate:
    name: str
    spec: str
    current: str
    wanted: str
    latest: str
    state: str
    detail: str

    @property
    def update_available(self) -> bool:
        return self.state in {"update", "pinned"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "spec": self.spec,
            "current": self.current,
            "wanted": self.wanted,
            "latest": self.latest,
            "state": self.state,
            "detail": self.detail,
            "update_available": self.update_available,
        }


@dataclass(frozen=True)
class ProfileReport:
    name: str
    directory: str
    total: int
    plugins: tuple[PluginUpdate, ...] = ()
    error: str | None = None

    @property
    def updates(self) -> tuple[PluginUpdate, ...]:
        return tuple(plugin for plugin in self.plugins if plugin.update_available)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dir": self.directory,
            "total": self.total,
            "update_count": len(self.updates),
            "plugins": [plugin.as_dict() for plugin in self.plugins],
            "error": self.error,
        }


@dataclass(frozen=True)
class UpdateReport:
    checked_at: str
    dsh: DshUpdate
    profile: ProfileReport
    errors: tuple[str, ...] = ()

    @property
    def update_count(self) -> int:
        return int(self.dsh.update_available) + len(self.profile.updates)

    @property
    def checked(self) -> bool:
        return bool(self.dsh.current) or self.profile.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "dsh": self.dsh.as_dict(),
            "profile": self.profile.as_dict(),
            "update_count": self.update_count,
            "errors": list(self.errors),
        }


# ── 依赖规格 ──────────────────────────────────────────────────────────
def spec_kind(spec: str) -> str:
    value = (spec or "").strip()
    lower = value.lower()
    if lower.startswith(("file:", "link:", "workspace:", "portal:", "patch:")):
        return "local"
    if lower.startswith(("git+", "git:", "github:", "gitlab:", "bitbucket:", "http://", "https://")):
        return "remote"
    if lower.startswith("npm:"):
        return "alias"
    if SHORTHAND_RE.match(value):
        return "remote"
    return "registry"


def _is_pinned(spec: str) -> bool:
    return bool(PINNED_RE.match((spec or "").strip()))


def _entry_for(
    name: str,
    spec: str,
    entries: dict[str, dict[str, str]],
) -> dict[str, str] | None:
    if name in entries:
        return entries[name]
    if spec_kind(spec) == "alias":
        prefix = name + ":"
        for key, value in entries.items():
            if key.startswith(prefix):
                return value
    return None


def _dependencies(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for key in ("dependencies", "optionalDependencies", "devDependencies"):
        value = manifest.get(key)
        if not isinstance(value, dict):
            continue
        for name, spec in value.items():
            if name in seen:
                continue
            seen.add(name)
            rows.append((str(name), spec if isinstance(spec, str) else ""))
    return rows


def parse_outdated(payload: Any) -> dict[str, dict[str, str]]:
    if not isinstance(payload, dict):
        return {}
    entries: dict[str, dict[str, str]] = {}
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        fields = {key: str(item) for key, item in value.items() if isinstance(item, (str, int, float, bool))}
        entries[str(key)] = fields
    return entries


def _outdated_entries(
    settings: Settings,
    profile: str,
    directory: Path,
    timeout: float,
) -> tuple[dict[str, dict[str, str]], str | None]:
    errors: list[str] = []
    npm = shutil.which("npm")
    if npm is not None:
        result = run_command([npm, "outdated", "--json", "--long"], cwd=directory, timeout=timeout)
        payload = _load_json(result.stdout)
        if isinstance(payload, dict):
            return parse_outdated(payload), None
        errors.append(f"npm outdated: {_tail(result.stderr or result.stdout) or f'exit {result.returncode}'}")

    try:
        node = discovery.node_exe(settings.node)
        bin_js = discovery.dsh_bin(settings.dsh_bin)
        result = run_command(
            [
                str(node),
                str(bin_js),
                "plugin",
                "--profile",
                profile,
                "outdated",
                "--format",
                "json",
            ],
            cwd=directory,
            timeout=timeout,
        )
        payload = _load_json(result.stdout)
        if isinstance(payload, dict):
            return parse_outdated(payload), None
        detail = _tail(result.stderr or result.stdout) or f"exit {result.returncode}"
        errors.append(f"dsh plugin outdated: {detail}")
    except Exception as exc:  # noqa: BLE001 - 每种失败都作为诊断返回
        errors.append(f"dsh plugin outdated: {type(exc).__name__}: {exc}")

    return {}, "；".join(errors)


def _profile_report(
    settings: Settings,
    profile: str,
    timeout: float,
) -> ProfileReport:
    try:
        directory = profile_dir(profile)
    except ValueError as exc:
        return ProfileReport(profile, "", 0, error=str(exc))

    manifest_path = directory / "package.json"
    try:
        manifest = json.loads(manifest_path.read_text("utf-8"))
    except FileNotFoundError:
        return ProfileReport(profile, str(directory), 0, error=f"profile 未初始化：{manifest_path}")
    except (OSError, json.JSONDecodeError) as exc:
        return ProfileReport(profile, str(directory), 0, error=f"读取 {manifest_path} 失败：{exc}")
    if not isinstance(manifest, dict):
        return ProfileReport(profile, str(directory), 0, error=f"{manifest_path} 不是对象")

    dependencies = _dependencies(manifest)
    entries, outdated_error = _outdated_entries(settings, profile, directory, timeout)

    plugins: list[PluginUpdate] = []
    for name, spec in dependencies:
        kind = spec_kind(spec)
        installed = installed_plugin_version(directory, name)
        entry = _entry_for(name, spec, entries) if kind == "registry" else None

        current = str((entry or {}).get("current") or installed or "").strip()
        wanted = str((entry or {}).get("wanted") or "").strip()
        latest = str((entry or {}).get("latest") or "").strip()

        if kind != "registry":
            plugins.append(
                PluginUpdate(
                    name,
                    spec,
                    current,
                    wanted,
                    latest,
                    "unsupported",
                    "非 registry 依赖，跳过自动更新",
                )
            )
            continue

        if current in {"", "missing"}:
            plugins.append(
                PluginUpdate(name, spec, current or "missing", wanted, latest, "missing", "未安装")
            )
            continue

        if entry is not None and latest and (current == latest or compare_versions(latest, current) == 0):
            plugins.append(PluginUpdate(name, spec, current, wanted, latest, "current", "已是最新"))
            continue

        if entry is not None and latest:
            newer = compare_versions(latest, current)
            if newer is None:
                plugins.append(PluginUpdate(name, spec, current, wanted, latest, "unknown", "无法比较版本"))
                continue
            if newer == -1:
                plugins.append(PluginUpdate(name, spec, current, wanted, latest, "current", "已是最新"))
                continue
            if wanted and compare_versions(wanted, current) == 1:
                if compare_versions(latest, wanted) == 1:
                    detail = f"现有范围可升到 {wanted}；最新版本需改范围"
                else:
                    detail = "现有范围可升级"
                state = "update"
            elif _is_pinned(spec):
                state = "pinned"
                detail = f"版本锁定为 {spec}"
            else:
                state = "update"
                detail = "需要改 package.json 的范围"
            plugins.append(PluginUpdate(name, spec, current, wanted, latest, state, detail))
            continue

        plugins.append(
            PluginUpdate(
                name,
                spec,
                current,
                wanted,
                latest or current,
                "current",
                "已是最新",
            )
        )

    error = outdated_error
    return ProfileReport(profile, str(directory), len(dependencies), tuple(plugins), error)


def _dsh_update(settings: Settings, timeout: float) -> DshUpdate:
    try:
        package_root, manifest = installed_dsh_package(settings)
    except Exception as exc:  # noqa: BLE001 - 检查结果显示具体原因
        return DshUpdate(DSH_PACKAGE, "", "", False, False, None, "", error=f"{type(exc).__name__}: {exc}")

    name = str(manifest.get("name") or DSH_PACKAGE)
    current = str(manifest.get("version") or "").strip()
    latest, manager_used, lookup_error = _latest_version(name, cwd=package_root.parent, timeout=timeout)
    install = f"npm install -g {name}@latest"
    if not current:
        return DshUpdate(name, current, latest, False, False, manager_used, install, error="当前版本为空")
    if not latest:
        return DshUpdate(name, current, latest, False, False, manager_used, install, error=lookup_error)
    if parse_version(current) is None or parse_version(latest) is None:
        return DshUpdate(
            name,
            current,
            latest,
            False,
            False,
            manager_used,
            install,
            error="无法用 semver 比较当前版本与最新版本",
        )

    newer = is_newer(latest, current)
    manager = (
        _global_manager(
            package_root,
            explicit=settings.dsh_bin is not None,
            timeout=timeout,
        )
        if newer
        else None
    )
    if manager == "npm":
        install = f"npm install -g {name}@{latest}"
    elif manager == "pnpm":
        install = f"pnpm add -g {name}@{latest}"
    elif newer:
        install = f"npm install -g {name}@{latest}"

    detail = ""
    if newer and manager is None:
        detail = "未识别 dsh 的全局包管理器，请在终端手动升级"
        if settings.dsh_bin is not None:
            detail = "dsh 路径是显式指定的，需手动升级"

    return DshUpdate(
        name,
        current,
        latest,
        newer,
        manager is not None,
        manager,
        install,
        detail,
        None,
    )


def check(settings: Settings, *, profile: str = "web", timeout: float = DEFAULT_TIMEOUT) -> UpdateReport:
    """并行检查 dsh 与指定 profile；失败作为报告字段返回，不抛异常。"""
    with ThreadPoolExecutor(max_workers=2) as pool:
        dsh_future = pool.submit(_dsh_update, settings, timeout)
        profile_future = pool.submit(_profile_report, settings, profile, timeout)
        dsh = dsh_future.result()
        profile_report = profile_future.result()

    errors: list[str] = []
    if dsh.error:
        errors.append(f"dsh: {dsh.error}")
    if profile_report.error:
        errors.append(f"profile {profile}: {profile_report.error}")
    return UpdateReport(
        datetime.now().isoformat(timespec="seconds"),
        dsh,
        profile_report,
        tuple(errors),
    )


# ── 文本输出 ──────────────────────────────────────────────────────────
def _display_width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in str(text))


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def format_report(report: UpdateReport) -> str:
    dsh = report.dsh
    lines: list[str] = []
    if dsh.current and dsh.latest:
        if dsh.update_available:
            lines.append(f"dsh  {dsh.name}  {dsh.current} → {dsh.latest}")
            if dsh.install:
                lines.append(f"     安装: {dsh.install}")
            if dsh.detail:
                lines.append(f"     {dsh.detail}")
        elif dsh.error:
            lines.append(f"dsh  {dsh.name}  {dsh.current}  检查失败: {dsh.error}")
        else:
            lines.append(f"dsh  {dsh.name}  {dsh.current}  已是最新")
    elif dsh.error:
        lines.append(f"dsh  检查失败: {dsh.error}")

    profile = report.profile
    lines.append("")
    lines.append(f"profile {profile.name}  {profile.directory or '-'}")
    if profile.error:
        lines.append(f"  警告: {profile.error}")
    if profile.plugins:
        lines.append(f"  {profile.total} 个插件，{len(profile.updates)} 个可更新")
        updates = [plugin for plugin in profile.plugins if plugin.update_available]
        if updates:
            width = max(_display_width(plugin.name) for plugin in updates)
            for plugin in updates:
                lines.append(
                    f"  {_pad(plugin.name, width)}  {plugin.current} → {plugin.latest}  ({plugin.detail})"
                )
        elif not profile.error:
            lines.append("  已是最新")
    elif not profile.error:
        lines.append("  没有安装插件")

    return "\n".join(lines)
