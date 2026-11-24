"""服务注册表：唯一允许出现具体服务名的地方。"""

from __future__ import annotations

from typing import Any

from ..context import ServiceContext
from .base import ServiceSpec
from .dsh.adapter import DshAdapter
from .dsh.settings import Settings as DshSettings  # noqa: F401 - 供类型检查/外部引用
from .dsh.settings import load as load_dsh
from .jupyter.adapter import JupyterAdapter
from .jupyter.settings import Settings as JupyterSettings  # noqa: F401
from .jupyter.settings import load as load_jupyter

SERVICE_IDS = ("dsh", "jupyter")


def spec(service_id: str) -> ServiceSpec:
    """服务静态元数据；不需要构建设置/adapter，供错误占位和导航使用。"""
    if service_id == "dsh":
        return DshAdapter.spec
    if service_id == "jupyter":
        return JupyterAdapter.spec
    raise KeyError(f"未知服务：{service_id}")


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
        adapter = JupyterAdapter(settings, None, runtime.memory)
    else:
        raise KeyError(f"未知服务：{service_id}")
    return ServiceContext(
        runtime=runtime,
        service_id=service_id,
        settings=settings,
        adapter=adapter,
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
