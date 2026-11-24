"""dsh / Jupyter 共用的监听地址、端口、浏览器与窗口配置解析。"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from .. import config as config_mod
from .. import paths


@dataclass(frozen=True)
class CommonSettings:
    host: str = "127.0.0.1"
    port: int = 0
    port_explicit: bool = False
    browser: str | None = None
    ozone: str = "auto"
    profile_dir: Path = field(default_factory=paths.profile_dir)
    profile_explicit: bool = False
    width_ratio: float = config_mod.WindowSettings().width_ratio
    height_ratio: float = config_mod.WindowSettings().height_ratio
    min_width: int = config_mod.WindowSettings().min_width
    min_height: int = config_mod.WindowSettings().min_height
    start_timeout: float = config_mod.DEFAULT_START_TIMEOUT
    dedupe: bool = True
    single_window: bool = False

    def window_kwargs(self) -> dict[str, Any]:
        return {
            "width_ratio": self.width_ratio,
            "height_ratio": self.height_ratio,
            "min_width": self.min_width,
            "min_height": self.min_height,
        }


@dataclass(frozen=True)
class ResolvedCommon:
    host: str
    port: int
    port_explicit: bool
    browser: str | None
    ozone: str
    profile_dir: Path
    profile_explicit: bool
    width_ratio: float
    height_ratio: float
    min_width: int
    min_height: int
    start_timeout: float
    dedupe: bool
    single_window: bool

    def as_kwargs(self) -> dict[str, Any]:
        return {item.name: getattr(self, item.name) for item in fields(type(self))}


def resolve_common(
    cfg: config_mod.Config,
    *,
    section_name: str,
    env_prefix: str,
    host: str | None,
    port: int | None,
    browser: str | None,
    ozone: str | None,
    profile_dir: str | Path | None,
    dedupe: bool | None,
    start_timeout: float | None,
    default_port: int,
    default_start_timeout: float,
    default_profile: Path,
    legacy_root: bool,
    launcher_timeout: bool,
) -> ResolvedCommon:
    section = cfg.section(section_name)

    def env(name: str) -> str | None:
        return config_mod.env(name, env_prefix)

    def value(key: str, default: Any) -> Any:
        if key in section:
            return section[key]
        if legacy_root and key in cfg.raw:
            return cfg.raw[key]
        return default

    requested_port = port if port is not None else env("PORT") or value("port", None)
    resolved_profile = profile_dir or env("PROFILE_DIR") or value("profile_dir", None)
    if cfg.ui.single_window:
        # Chromium 必须共用 user-data-dir 才能把控制台和服务放进同一窗口。
        resolved_profile = paths.tabbed_profile()

    resolved_ozone = str(ozone or cfg.ui.ozone or "auto").strip().lower()
    if resolved_ozone not in config_mod.OZONE_MODES:
        raise ValueError(f"ozone 只能是 {' / '.join(config_mod.OZONE_MODES)}，收到 {resolved_ozone!r}")

    timeout_default = (
        cfg.launcher.start_timeout if launcher_timeout else value("start_timeout", default_start_timeout)
    )
    resolved_timeout = float(start_timeout or env("START_TIMEOUT") or timeout_default)

    return ResolvedCommon(
        host=str(host or env("HOST") or value("host", "127.0.0.1")),
        port=int(requested_port) if requested_port is not None else default_port,
        port_explicit=requested_port is not None,
        browser=str(browser or cfg.ui.browser or "") or None,
        ozone=resolved_ozone,
        profile_dir=Path(resolved_profile).expanduser() if resolved_profile else default_profile,
        profile_explicit=resolved_profile is not None,
        width_ratio=cfg.ui.window.width_ratio,
        height_ratio=cfg.ui.window.height_ratio,
        min_width=cfg.ui.window.min_width,
        min_height=cfg.ui.window.min_height,
        start_timeout=resolved_timeout,
        dedupe=cfg.ui.dedupe if dedupe is None else dedupe,
        single_window=cfg.ui.single_window,
    )


def settings_kwargs(common: ResolvedCommon) -> dict[str, Any]:
    """给具体 ``Settings`` 数据类的构造参数；保留该函数作为类型边界。"""
    return common.as_kwargs()


__all__ = ["CommonSettings", "ResolvedCommon", "resolve_common", "settings_kwargs"]
