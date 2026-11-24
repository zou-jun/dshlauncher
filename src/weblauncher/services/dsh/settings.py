"""dsh 配置：CLI > WEBLAUNCHER_DSH_* > config.toml 的 [dsh]/[ui]/[launcher] > 默认值。

旧版把 dsh 与窗口字段平铺在 ``config.toml`` 根上；读取时继续兼容，
写入只走新结构（``config set dsh.port``）。
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ... import config as config_mod
from ... import paths

ENV_PREFIX = "WEBLAUNCHER_DSH_"
DEFAULT_HOST = "127.0.0.1"
#: 历史默认端口；不可 bind 时由 ports.candidates() 依次回退到 18080 起。
DEFAULT_PORT = 3080
DEFAULT_START_TIMEOUT = 120.0
OZONE_MODES = config_mod.OZONE_MODES


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    #: port 是否来自 CLI / 环境变量 / config.toml：显式指定的端口不自动改。
    port_explicit: bool = False
    #: 服务工作目录：默认系统临时目录，可用 WEBLAUNCHER_DSH_CWD / --cwd 覆盖。
    work_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    node: Path | None = None
    dsh_bin: Path | None = None
    browser: str | None = None
    ozone: str = "auto"
    profile_dir: Path = field(default_factory=paths.profile_dir)
    #: profile_dir 是否来自 CLI / 环境变量 / config.toml：否则跟随运行时 Paths。
    profile_explicit: bool = False
    width_ratio: float = config_mod.WindowSettings().width_ratio
    height_ratio: float = config_mod.WindowSettings().height_ratio
    min_width: int = config_mod.WindowSettings().min_width
    min_height: int = config_mod.WindowSettings().min_height
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
    return config_mod.env(name, ENV_PREFIX)


def _value(cfg: config_mod.Config, section: dict[str, Any], key: str, default: Any) -> Any:
    if key in section:
        return section[key]
    if key in cfg.raw:
        return cfg.raw[key]
    return default


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
    config: config_mod.Config | None = None,
) -> Settings:
    cfg = config or config_mod.load()
    section = cfg.section("dsh")
    defaults = Settings()

    resolved_ozone = str(ozone or cfg.ui.ozone or defaults.ozone).strip().lower()
    if resolved_ozone not in OZONE_MODES:
        raise ValueError(f"ozone 只能是 {' / '.join(OZONE_MODES)}，收到 {resolved_ozone!r}")

    resolved_work_dir = work_dir or _env("CWD") or _value(cfg, section, "work_dir", None)
    profile_value = profile_dir or _env("PROFILE_DIR") or _value(cfg, section, "profile_dir", None)
    requested_port = port if port is not None else _env("PORT") or _value(cfg, section, "port", None)
    resolved_port = int(requested_port) if requested_port is not None else defaults.port
    resolved_dedupe = dedupe if dedupe is not None else cfg.ui.dedupe

    node_value = node or _env("NODE") or _value(cfg, section, "node", None)
    dsh_value = dsh_bin or _env("BIN") or _value(cfg, section, "dsh_bin", None)
    return Settings(
        host=str(host or _env("HOST") or _value(cfg, section, "host", defaults.host)),
        port=resolved_port,
        port_explicit=requested_port is not None,
        work_dir=Path(resolved_work_dir).expanduser() if resolved_work_dir else defaults.work_dir,
        node=Path(node_value).expanduser() if node_value else None,
        dsh_bin=Path(dsh_value).expanduser() if dsh_value else None,
        browser=str(browser or cfg.ui.browser or "") or None,
        ozone=resolved_ozone,
        profile_dir=Path(profile_value).expanduser() if profile_value else defaults.profile_dir,
        profile_explicit=profile_value is not None,
        width_ratio=cfg.ui.window.width_ratio,
        height_ratio=cfg.ui.window.height_ratio,
        min_width=cfg.ui.window.min_width,
        min_height=cfg.ui.window.min_height,
        start_timeout=float(
            start_timeout or _env("START_TIMEOUT") or cfg.launcher.start_timeout or defaults.start_timeout
        ),
        dedupe=resolved_dedupe,
    )
