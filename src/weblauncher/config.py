"""全局配置：``config.toml`` 的读取、分层与原地修改。

CLI > 环境变量 > config.toml > 默认值 的优先级由各服务自己的
``settings.load(...)`` 实现；这里只负责文件层与共享的 ``[launcher]`` /
``[ui]`` 段。``config set`` 按行修改，保留用户手写的注释与顺序。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import geometry

ENV_PREFIX = "WEBLAUNCHER_"
DEFAULT_START_TIMEOUT = 120.0
OZONE_MODES = ("auto", "x11", "wayland")
SINGLE_WINDOW_PROFILES = ("tabbed", "daily")


def env(name: str, prefix: str = ENV_PREFIX) -> str | None:
    value = os.environ.get(prefix + name, "").strip()
    return value or None


def flag(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class WindowSettings:
    width_ratio: float = geometry.WIDTH_RATIO
    height_ratio: float = geometry.HEIGHT_RATIO
    min_width: int = geometry.MIN_WIDTH
    min_height: int = geometry.MIN_HEIGHT

    def kwargs(self) -> dict[str, Any]:
        return {
            "width_ratio": self.width_ratio,
            "height_ratio": self.height_ratio,
            "min_width": self.min_width,
            "min_height": self.min_height,
        }


@dataclass(frozen=True)
class UiSettings:
    browser: str | None = None
    ozone: str = "auto"
    dedupe: bool = True
    #: 控制台与所有服务共用同一个浏览器窗口，以普通标签页而不是 --app 窗口打开。
    single_window: bool = False
    #: 单窗口模式使用的浏览器配置：tabbed = 独立 tabbed-browser，daily = 日常 Chrome。
    single_window_profile: str = "tabbed"
    window: WindowSettings = WindowSettings()

    @property
    def daily_profile(self) -> bool:
        return self.single_window and self.single_window_profile == "daily"


@dataclass(frozen=True)
class LauncherSettings:
    start_timeout: float = DEFAULT_START_TIMEOUT
    tray_exit_stops_services: bool = True


@dataclass(frozen=True)
class Config:
    launcher: LauncherSettings
    ui: UiSettings
    raw: dict[str, Any]

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name)
        return value if isinstance(value, dict) else {}


def read_raw(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _legacy(raw: dict[str, Any], modern: dict[str, Any], key: str, default: Any) -> Any:
    """旧版配置把 dsh/UI 字段平铺在根上；读取时仍兼容，写入只写新结构。"""
    if key in modern:
        return modern[key]
    if key in raw:
        return raw[key]
    return default


def load(path: Path | None = None) -> Config:
    from . import paths as paths_mod

    raw = read_raw(path or paths_mod.config_path())
    ui_value = raw.get("ui")
    ui_raw: dict[str, Any] = ui_value if isinstance(ui_value, dict) else {}
    window_value = ui_raw.get("window")
    window_raw: dict[str, Any] = window_value if isinstance(window_value, dict) else {}
    legacy_value = raw.get("window")
    legacy_window: dict[str, Any] = legacy_value if isinstance(legacy_value, dict) else {}
    launcher_value = raw.get("launcher")
    launcher_raw: dict[str, Any] = launcher_value if isinstance(launcher_value, dict) else {}

    ozone = str(env("OZONE") or _legacy(raw, ui_raw, "ozone", "auto")).strip().lower()
    if ozone not in OZONE_MODES:
        raise ValueError(f"ozone 只能是 {' / '.join(OZONE_MODES)}，收到 {ozone!r}")
    single_window_profile = (
        str(env("SINGLE_WINDOW_PROFILE") or _legacy(raw, ui_raw, "single_window_profile", "tabbed"))
        .strip()
        .lower()
    )
    if single_window_profile not in SINGLE_WINDOW_PROFILES:
        raise ValueError(
            "single_window_profile 只能是 "
            f"{' / '.join(SINGLE_WINDOW_PROFILES)}，收到 {single_window_profile!r}"
        )

    window = WindowSettings(
        width_ratio=float(
            os.environ.get(ENV_PREFIX + "WIDTH_RATIO")
            or window_raw.get("width_ratio")
            or legacy_window.get("width_ratio")
            or geometry.WIDTH_RATIO
        ),
        height_ratio=float(
            os.environ.get(ENV_PREFIX + "HEIGHT_RATIO")
            or window_raw.get("height_ratio")
            or legacy_window.get("height_ratio")
            or geometry.HEIGHT_RATIO
        ),
        min_width=int(window_raw.get("min_width") or legacy_window.get("min_width") or geometry.MIN_WIDTH),
        min_height=int(
            window_raw.get("min_height") or legacy_window.get("min_height") or geometry.MIN_HEIGHT
        ),
    )
    return Config(
        launcher=LauncherSettings(
            start_timeout=float(
                env("START_TIMEOUT") or _legacy(launcher_raw, raw, "start_timeout", DEFAULT_START_TIMEOUT)
            ),
            tray_exit_stops_services=flag(_legacy(launcher_raw, raw, "tray_exit_stops_services", True), True),
        ),
        ui=UiSettings(
            browser=str(env("BROWSER") or _legacy(raw, ui_raw, "browser", "") or "") or None,
            ozone=ozone,
            dedupe=env("NO_DEDUPE") is None and flag(_legacy(raw, ui_raw, "dedupe", True), True),
            single_window=flag(
                env("SINGLE_WINDOW") or _legacy(raw, ui_raw, "single_window", False),
                False,
            ),
            single_window_profile=single_window_profile,
            window=window,
        ),
        raw=raw,
    )


# ── config set / unset（按行编辑，保留注释） ─────────────────────────
def parse_value(text: str) -> Any:
    """把命令行里的字面量转成 TOML 值：true/false、数字、带引号字符串。"""
    value = text.strip()
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return tomllib.loads("v = " + value)["v"]
    except (tomllib.TOMLDecodeError, KeyError):
        return text


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_value(item) for item in value) + "]"
    return format_value(str(value))


def _split_dotted(key: str) -> tuple[str, ...]:
    parts = [part for part in key.split(".") if part]
    if not parts:
        raise ValueError("配置键不能为空")
    return tuple(parts)


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    header = f"[{section}]"
    start = None
    for index, line in enumerate(lines):
        if line.strip() == header:
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].lstrip().startswith("["):
            end = index
            break
    return start, end


def set_value(path: Path, dotted: str, value: Any) -> None:
    parts = _split_dotted(dotted)
    key = parts[-1]
    section = ".".join(parts[:-1])
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError:
        lines = []
    assignment = f"{key} = {format_value(value)}"

    if section:
        bounds = _section_bounds(lines, section)
        if bounds is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"[{section}]")
            lines.append(assignment)
        else:
            start, end = bounds
            replaced = False
            for index in range(start + 1, end):
                stripped = lines[index].strip()
                if stripped.startswith(key + " ") or stripped.startswith(key + "="):
                    lines[index] = assignment
                    replaced = True
                    break
            if not replaced:
                insert_at = end
                while insert_at > start + 1 and not lines[insert_at - 1].strip():
                    insert_at -= 1
                lines.insert(insert_at, assignment)
    else:
        replaced = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("["):
                break
            if stripped.startswith(key + " ") or stripped.startswith(key + "="):
                lines[index] = assignment
                replaced = True
                break
        if not replaced:
            insert_at = 0
            for index, line in enumerate(lines):
                if line.strip().startswith("["):
                    insert_at = index
                    break
                insert_at = index + 1
            lines.insert(insert_at, assignment)
    path.parent.mkdir(parents=True, exist_ok=True)
    from . import paths as paths_mod

    paths_mod.write_atomic(path, "\n".join(lines) + "\n")


def unset_value(path: Path, dotted: str) -> bool:
    parts = _split_dotted(dotted)
    key = parts[-1]
    section = ".".join(parts[:-1])
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError:
        return False

    def matches(index: int) -> bool:
        stripped = lines[index].strip()
        return stripped.startswith(key + " ") or stripped.startswith(key + "=")

    removed = False
    if section:
        bounds = _section_bounds(lines, section)
        if bounds is None:
            return False
        start, end = bounds
        for index in range(start + 1, end):
            if matches(index):
                del lines[index]
                removed = True
                break
    else:
        for index, line in enumerate(lines):
            if line.strip().startswith("["):
                break
            if matches(index):
                del lines[index]
                removed = True
                break
    if removed:
        from . import paths as paths_mod

        paths_mod.write_atomic(path, "\n".join(lines) + "\n")
    return removed


def get_value(path: Path, dotted: str) -> Any:
    data: Any = read_raw(path)
    for part in _split_dotted(dotted):
        if not isinstance(data, dict) or part not in data:
            raise KeyError(dotted)
        data = data[part]
    return data
