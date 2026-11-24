"""Jupyter 配置：CLI > WEBLAUNCHER_JUPYTER_* > config.toml 的 [jupyter] > memory.toml > 默认值。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ... import config as config_mod
from ... import memory as memory_mod
from ... import paths

ENV_PREFIX = "WEBLAUNCHER_JUPYTER_"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888
DEFAULT_START_TIMEOUT = 60.0
DEFAULT_BASE_URL = "/"


def _normalize_base(value: str) -> str:
    base = "/" + value.strip().strip("/")
    return base + "/" if base != "/" else "/"


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    port_explicit: bool = False
    root_dir: Path = field(default_factory=Path.home)
    base_url: str = DEFAULT_BASE_URL
    jupyter_bin: Path | None = None
    #: 固定 token；省略时每次启动随机生成。
    token: str | None = None
    #: 新 notebook 的默认内核（kernelspec id）。
    kernel: str | None = None
    browser: str | None = None
    ozone: str = "auto"
    profile_dir: Path = field(default_factory=lambda: paths.Paths.current().service("jupyter").profile)
    profile_explicit: bool = False
    width_ratio: float = config_mod.WindowSettings().width_ratio
    height_ratio: float = config_mod.WindowSettings().height_ratio
    min_width: int = config_mod.WindowSettings().min_width
    min_height: int = config_mod.WindowSettings().min_height
    start_timeout: float = DEFAULT_START_TIMEOUT
    dedupe: bool = True
    remember_per_workdir: bool = True

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
    return default


def effective_kernel(memory: dict[str, Any], workdir: Path, *, remember: bool = True) -> str | None:
    table = memory_mod.section(memory, "jupyter")
    if remember:
        mapping = table.get("workdir_kernels")
        if isinstance(mapping, dict):
            for key, value in mapping.items():
                try:
                    same = Path(key).expanduser().resolve() == workdir
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

    remember_raw = _value(cfg, section, "remember_per_workdir", None)
    remember = config_mod.flag(remember_raw, True) if remember_raw is not None else True
    if "remember_per_workdir" in memory_mod.section(mem, "jupyter"):
        remember = config_mod.flag(memory_mod.section(mem, "jupyter")["remember_per_workdir"], remember)

    root_value = (
        root
        or _env("ROOT")
        or _value(cfg, section, "root_dir", None)
        or memory_mod.get(mem, "jupyter", "workdir", None)
        or Path.home()
    )
    root_dir = Path(root_value).expanduser()

    requested_port = port if port is not None else _env("PORT") or _value(cfg, section, "port", None)
    kernel_value = (
        kernel
        or _env("KERNEL")
        or effective_kernel(mem, root_dir, remember=remember)
        or _value(cfg, section, "kernel", None)
    )
    profile_value = profile_dir or _env("PROFILE_DIR") or _value(cfg, section, "profile_dir", None)
    jupyter_value = jupyter_bin or _env("JUPYTER_BIN") or _value(cfg, section, "jupyter_bin", None)
    base_value = base_url or _env("BASE_URL") or _value(cfg, section, "base_url", DEFAULT_BASE_URL)

    resolved_ozone = str(ozone or cfg.ui.ozone or defaults.ozone).strip().lower()
    if resolved_ozone not in config_mod.OZONE_MODES:
        raise ValueError(f"ozone 只能是 {' / '.join(config_mod.OZONE_MODES)}，收到 {resolved_ozone!r}")

    return Settings(
        host=str(host or _env("HOST") or _value(cfg, section, "host", defaults.host)),
        port=int(requested_port) if requested_port is not None else defaults.port,
        port_explicit=requested_port is not None,
        root_dir=root_dir,
        base_url=_normalize_base(str(base_value)),
        jupyter_bin=Path(jupyter_value).expanduser() if jupyter_value else None,
        token=str(_env("TOKEN") or _value(cfg, section, "token", "") or "") or None,
        kernel=str(kernel_value) if kernel_value else None,
        browser=str(browser or cfg.ui.browser or "") or None,
        ozone=resolved_ozone,
        profile_dir=Path(profile_value).expanduser() if profile_value else defaults.profile_dir,
        profile_explicit=profile_value is not None,
        width_ratio=cfg.ui.window.width_ratio,
        height_ratio=cfg.ui.window.height_ratio,
        min_width=cfg.ui.window.min_width,
        min_height=cfg.ui.window.min_height,
        start_timeout=float(
            start_timeout
            or _env("START_TIMEOUT")
            or _value(cfg, section, "start_timeout", DEFAULT_START_TIMEOUT)
        ),
        dedupe=cfg.ui.dedupe if dedupe is None else dedupe,
        remember_per_workdir=remember,
    )
