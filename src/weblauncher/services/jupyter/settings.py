"""Jupyter 配置：CLI > WEBLAUNCHER_JUPYTER_* > config.toml 的 [jupyter] > memory.toml > 默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ... import config as config_mod
from ... import memory as memory_mod
from ... import paths
from ..common_settings import CommonSettings, resolve_common, settings_kwargs

ENV_PREFIX = "WEBLAUNCHER_JUPYTER_"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888
DEFAULT_START_TIMEOUT = 60.0
DEFAULT_BASE_URL = "/"


def _normalize_base(value: str) -> str:
    base = "/" + value.strip().strip("/")
    return base + "/" if base != "/" else "/"


@dataclass(frozen=True)
class Settings(CommonSettings):
    port: int = DEFAULT_PORT
    start_timeout: float = DEFAULT_START_TIMEOUT
    #: Jupyter 必须有自己的 profile；继承 CommonSettings 的全局 profile 会与 dsh 共用 cookie。
    profile_dir: Path = field(default_factory=lambda: paths.Paths.current().service("jupyter").profile)
    root_dir: Path = field(default_factory=Path.home)
    base_url: str = DEFAULT_BASE_URL
    jupyter_bin: Path | None = None
    #: 固定 token；省略时每次启动随机生成。
    token: str | None = None
    #: 新 notebook 的默认内核（kernelspec id）。
    kernel: str | None = None
    remember_per_workdir: bool = True


def _env(name: str) -> str | None:
    return config_mod.env(name, ENV_PREFIX)


def _value(section: dict[str, Any], key: str, default: Any) -> Any:
    if key in section:
        return section[key]
    return default


def effective_kernel(memory: dict[str, Any], workdir: Path, *, remember: bool = True) -> str | None:
    table = memory_mod.section(memory, "jupyter")
    if remember:
        mapping = table.get("workdir_kernels")
        if isinstance(mapping, dict):
            for key, value in mapping.items():
                try:
                    same = Path(key).expanduser().resolve() == workdir.expanduser().resolve()
                except OSError:
                    same = str(key) == str(workdir)
                if same and isinstance(value, str) and value:
                    return value
    kernel = table.get("kernel")
    return str(kernel) if isinstance(kernel, str) and kernel else None


def load(
    *,
    host: str | None = None,
    port: int | None = None,
    root: str | Path | None = None,
    kernel: str | None = None,
    jupyter_bin: str | Path | None = None,
    base_url: str | None = None,
    browser: str | None = None,
    ozone: str | None = None,
    profile_dir: str | Path | None = None,
    dedupe: bool | None = None,
    start_timeout: float | None = None,
    config: config_mod.Config | None = None,
    memory: dict[str, Any] | None = None,
) -> Settings:
    cfg = config or config_mod.load()
    mem = memory if memory is not None else memory_mod.load()
    section = cfg.section("jupyter")
    defaults = Settings()
    common = resolve_common(
        cfg,
        section_name="jupyter",
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
        legacy_root=False,
        launcher_timeout=False,
    )

    remember_raw = _value(section, "remember_per_workdir", None)
    remember = config_mod.flag(remember_raw, True) if remember_raw is not None else True
    if "remember_per_workdir" in memory_mod.section(mem, "jupyter"):
        remember = config_mod.flag(memory_mod.section(mem, "jupyter")["remember_per_workdir"], remember)

    root_value = (
        root
        or _env("ROOT")
        or _value(section, "root_dir", None)
        or memory_mod.get(mem, "jupyter", "workdir", None)
        or Path.home()
    )
    root_dir = Path(root_value).expanduser()
    kernel_value = (
        kernel
        or _env("KERNEL")
        or effective_kernel(mem, root_dir, remember=remember)
        or _value(section, "kernel", None)
    )
    jupyter_value = jupyter_bin or _env("BIN") or _value(section, "jupyter_bin", None)
    base_value = base_url or _env("BASE_URL") or _value(section, "base_url", DEFAULT_BASE_URL)

    return Settings(
        **settings_kwargs(common),
        root_dir=root_dir,
        base_url=_normalize_base(str(base_value)),
        jupyter_bin=Path(jupyter_value).expanduser() if jupyter_value else None,
        token=str(_env("TOKEN") or _value(section, "token", "") or "") or None,
        kernel=str(kernel_value) if kernel_value else None,
        remember_per_workdir=remember,
    )
