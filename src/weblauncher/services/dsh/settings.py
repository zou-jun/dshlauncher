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
from ..common_settings import CommonSettings, resolve_common, settings_kwargs

ENV_PREFIX = "WEBLAUNCHER_DSH_"
DEFAULT_HOST = "127.0.0.1"
#: 历史默认端口；不可 bind 时由 ports.candidates() 依次回退到 18080 起。
DEFAULT_PORT = 3080
DEFAULT_START_TIMEOUT = 120.0
OZONE_MODES = config_mod.OZONE_MODES


@dataclass(frozen=True)
class Settings(CommonSettings):
    port: int = DEFAULT_PORT
    start_timeout: float = DEFAULT_START_TIMEOUT
    #: 服务工作目录：默认系统临时目录，可用 WEBLAUNCHER_DSH_CWD / --cwd 覆盖。
    work_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    node: Path | None = None
    dsh_bin: Path | None = None


def _env(name: str) -> str | None:
    return config_mod.env(name, ENV_PREFIX)


def _legacy_value(cfg: config_mod.Config, section: dict[str, Any], key: str, default: Any) -> Any:
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
    common = resolve_common(
        cfg,
        section_name="dsh",
        env_prefix=ENV_PREFIX,
        host=host,
        port=port,
        browser=browser,
        ozone=ozone,
        profile_dir=profile_dir,
        dedupe=dedupe,
        start_timeout=start_timeout,
        default_port=defaults.port,
        default_start_timeout=defaults.start_timeout,
        default_profile=defaults.profile_dir,
        legacy_root=True,
        launcher_timeout=True,
    )

    work_dir_value = work_dir or _env("CWD") or _legacy_value(cfg, section, "work_dir", None)
    node_value = node or _env("NODE") or _legacy_value(cfg, section, "node", None)
    dsh_value = dsh_bin or _env("BIN") or _legacy_value(cfg, section, "dsh_bin", None)
    return Settings(
        **settings_kwargs(common),
        work_dir=Path(work_dir_value).expanduser() if work_dir_value else defaults.work_dir,
        node=Path(node_value).expanduser() if node_value else None,
        dsh_bin=Path(dsh_value).expanduser() if dsh_value else None,
    )
