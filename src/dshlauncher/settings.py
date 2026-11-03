"""配置分层：CLI 参数 > 环境变量 DSHLAUNCHER_* > <data>/config.toml > 默认值。"""

from __future__ import annotations

import os
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import geometry, paths

ENV_PREFIX = "DSHLAUNCHER_"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3080
DEFAULT_START_TIMEOUT = 120.0
#: Linux 上 Chrome 的显示后端：auto 交给 Chrome（Wayland 会话里是原生 Wayland），
#: x11 强制走 XWayland（这时窗口可以枚举/移动/置前），wayland 显式要求原生。
OZONE_MODES = ("auto", "x11", "wayland")


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    #: 服务工作目录：默认系统临时目录，可用 DSHLAUNCHER_CWD / --cwd 覆盖。
    work_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    node: Path | None = None
    dsh_bin: Path | None = None
    browser: str | None = None
    ozone: str = "auto"
    profile_dir: Path = field(default_factory=paths.profile_dir)
    width_ratio: float = geometry.WIDTH_RATIO
    height_ratio: float = geometry.HEIGHT_RATIO
    min_width: int = geometry.MIN_WIDTH
    min_height: int = geometry.MIN_HEIGHT
    start_timeout: float = DEFAULT_START_TIMEOUT
    dedupe: bool = True

    def window_kwargs(self) -> dict[str, Any]:
        return {
            "width_ratio": self.width_ratio,
            "height_ratio": self.height_ratio,
            "min_width": self.min_width,
            "min_height": self.min_height,
        }


def _env(name: str) -> str | None:
    value = os.environ.get(ENV_PREFIX + name, "").strip()
    return value or None


def _file_values() -> dict[str, Any]:
    try:
        with paths.config_path().open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _window_values() -> dict[str, Any]:
    window = _file_values().get("window")
    return window if isinstance(window, dict) else {}


def _ozone(value: Any) -> str:
    mode = str(value).strip().lower()
    if mode not in OZONE_MODES:
        raise ValueError(f"ozone 只能是 {' / '.join(OZONE_MODES)}，收到 {value!r}")
    return mode


def _flag(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def load(
    *,
    host: str | None = None,
    port: int | None = None,
    work_dir: str | Path | None = None,
    node: str | Path | None = None,
    dsh_bin: str | Path | None = None,
    browser: str | None = None,
    ozone: str | None = None,
    profile_dir: str | Path | None = None,
    dedupe: bool | None = None,
    start_timeout: float | None = None,
) -> Settings:
    cfg = _file_values()
    window = _window_values()
    defaults = Settings()

    resolved_work_dir = work_dir or _env("CWD") or cfg.get("work_dir")
    resolved_profile = profile_dir or _env("PROFILE_DIR") or cfg.get("profile_dir")
    resolved_ozone = _ozone(ozone or _env("OZONE") or cfg.get("ozone") or defaults.ozone)
    resolved_dedupe = dedupe
    if resolved_dedupe is None:
        resolved_dedupe = False if _env("NO_DEDUPE") is not None else _flag(cfg.get("dedupe"), True)

    return Settings(
        host=str(host or _env("HOST") or cfg.get("host") or defaults.host),
        port=int(port or _env("PORT") or cfg.get("port") or defaults.port),
        work_dir=Path(resolved_work_dir).expanduser() if resolved_work_dir else defaults.work_dir,
        node=Path(node or _env("NODE") or cfg.get("node") or "").expanduser()
        if (node or _env("NODE") or cfg.get("node"))
        else None,
        dsh_bin=Path(dsh_bin or _env("DSH_BIN") or cfg.get("dsh_bin") or "").expanduser()
        if (dsh_bin or _env("DSH_BIN") or cfg.get("dsh_bin"))
        else None,
        browser=str(browser or _env("BROWSER") or cfg.get("browser") or "") or None,
        ozone=resolved_ozone,
        profile_dir=Path(resolved_profile).expanduser() if resolved_profile else defaults.profile_dir,
        width_ratio=float(
            os.environ.get(ENV_PREFIX + "WIDTH_RATIO") or window.get("width_ratio") or defaults.width_ratio
        ),
        height_ratio=float(
            os.environ.get(ENV_PREFIX + "HEIGHT_RATIO") or window.get("height_ratio") or defaults.height_ratio
        ),
        min_width=int(window.get("min_width") or defaults.min_width),
        min_height=int(window.get("min_height") or defaults.min_height),
        start_timeout=float(
            start_timeout
            or os.environ.get(ENV_PREFIX + "START_TIMEOUT")
            or cfg.get("start_timeout")
            or defaults.start_timeout
        ),
        dedupe=resolved_dedupe,
    )
