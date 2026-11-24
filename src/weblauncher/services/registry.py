"""服务注册表：唯一允许出现具体服务名的地方。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..context import ServiceContext
from .dsh.adapter import DshAdapter
from .dsh.settings import Settings as DshSettings  # noqa: F401 - 供类型检查/外部引用
from .dsh.settings import load as load_dsh
from .jupyter import discovery as jupyter_discovery
from .jupyter.adapter import JupyterAdapter
from .jupyter.settings import Settings as JupyterSettings  # noqa: F401
from .jupyter.settings import load as load_jupyter

SERVICE_IDS = ("dsh", "jupyter")


@dataclass(frozen=True)
class ServiceDefinition:
    id: str
    label: str
    auto_start: bool
    open_on_start: bool


def _definition(service_id: str) -> ServiceDefinition:
    if service_id == "dsh":
        return ServiceDefinition("dsh", "dsh web", True, True)
    return ServiceDefinition("jupyter", "Jupyter Lab", False, False)


def build(
    runtime,
    service_id: str,
    *,
    cli: dict[str, Any] | None = None,
) -> ServiceContext:
    """按服务 id 组装 settings + adapter + context。"""
    options = cli or {}
    if service_id == "dsh":
        settings = load_dsh(config=runtime.config, **options)
        adapter = DshAdapter(settings, runtime.paths)
    elif service_id == "jupyter":
        settings = load_jupyter(config=runtime.config, memory=runtime.memory, **options)
        install = jupyter_discovery.find(settings.jupyter_bin)
        adapter = JupyterAdapter(settings, install, runtime.memory)
    else:
        raise KeyError(f"未知服务：{service_id}")
    definition = _definition(service_id)
    return ServiceContext(
        runtime=runtime,
        service_id=service_id,
        settings=settings,
        adapter=adapter,
        definition=definition,
    )


def ids() -> tuple[str, ...]:
    return SERVICE_IDS


def split(value: str) -> tuple[str, ...]:
    """把 ``all`` / 单个服务 / 逗号列表解析成 id 元组。"""
    if value.strip().lower() == "all":
        return SERVICE_IDS
    wanted = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [item for item in wanted if item not in SERVICE_IDS]
    if unknown:
        raise KeyError(f"未知服务：{', '.join(unknown)}；可选 {', '.join(SERVICE_IDS)} / all")
    return tuple(wanted)
