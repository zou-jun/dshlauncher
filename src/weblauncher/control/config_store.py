"""控制台配置：字段清单、读取快照与保留注释的写操作。"""

from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path
from typing import Any

from .. import config as config_mod
from .. import paths as paths_mod
from ..context import Runtime
from .errors import ControlError

CONFIG_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "key": "launcher.start_timeout",
        "label": "启动超时（秒）",
        "type": "number",
        "section": "launcher",
        "help": "等待服务就绪的最长时间",
    },
    {
        "key": "launcher.tray_exit_stops_services",
        "label": "退出时停止服务",
        "type": "boolean",
        "section": "launcher",
        "help": "Ctrl+C / 退出控制台时是否停止托管服务",
    },
    {
        "key": "ui.browser",
        "label": "浏览器",
        "type": "string",
        "section": "ui",
        "help": "chrome / edge / chromium / brave 或路径",
    },
    {
        "key": "ui.ozone",
        "label": "Linux 显示后端",
        "type": "select",
        "section": "ui",
        "choices": list(config_mod.OZONE_MODES),
    },
    {"key": "ui.dedupe", "label": "浏览器窗口去重", "type": "boolean", "section": "ui"},
    {
        "key": "ui.single_window",
        "label": "单窗口标签页",
        "type": "boolean",
        "section": "ui",
        "help": "控制台和所有服务共用一个 Chromium 窗口，以普通标签页打开",
    },
    {
        "key": "ui.single_window_profile",
        "label": "单窗口浏览器配置",
        "type": "select",
        "section": "ui",
        "choices": list(config_mod.SINGLE_WINDOW_PROFILES),
        "help": "tabbed: 独立 tabbed-browser；daily: 日常 Chrome 默认配置（仅 single_window 生效）",
    },
    {"key": "ui.window.width_ratio", "label": "窗口宽度比例", "type": "number", "section": "ui.window"},
    {"key": "ui.window.height_ratio", "label": "窗口高度比例", "type": "number", "section": "ui.window"},
    {"key": "ui.window.min_width", "label": "最小宽度", "type": "number", "section": "ui.window"},
    {"key": "ui.window.min_height", "label": "最小高度", "type": "number", "section": "ui.window"},
    {"key": "dsh.host", "label": "dsh 绑定地址", "type": "string", "section": "dsh"},
    {"key": "dsh.port", "label": "dsh 端口", "type": "number", "section": "dsh"},
    {"key": "dsh.work_dir", "label": "dsh 工作目录", "type": "path", "section": "dsh"},
    {"key": "dsh.node", "label": "node 路径", "type": "path", "section": "dsh"},
    {"key": "dsh.dsh_bin", "label": "dsh bin.js 路径", "type": "path", "section": "dsh"},
    {"key": "dsh.profile_dir", "label": "dsh 浏览器 profile", "type": "path", "section": "dsh"},
    {"key": "dsh.start_timeout", "label": "dsh 启动超时", "type": "number", "section": "dsh"},
    {"key": "jupyter.host", "label": "Jupyter 绑定地址", "type": "string", "section": "jupyter"},
    {"key": "jupyter.port", "label": "Jupyter 端口", "type": "number", "section": "jupyter"},
    {"key": "jupyter.root_dir", "label": "Jupyter 工作目录", "type": "path", "section": "jupyter"},
    {"key": "jupyter.jupyter_bin", "label": "jupyter-lab 路径", "type": "path", "section": "jupyter"},
    {"key": "jupyter.profile_dir", "label": "Jupyter 浏览器 profile", "type": "path", "section": "jupyter"},
    {"key": "jupyter.start_timeout", "label": "Jupyter 启动超时", "type": "number", "section": "jupyter"},
    {"key": "jupyter.base_url", "label": "Jupyter base_url", "type": "string", "section": "jupyter"},
    {"key": "jupyter.kernel", "label": "默认内核", "type": "string", "section": "jupyter"},
    {
        "key": "jupyter.remember_per_workdir",
        "label": "按目录记忆内核",
        "type": "boolean",
        "section": "jupyter",
    },
)


def snapshot(runtime: Runtime) -> dict[str, Any]:
    path = runtime.paths.config
    try:
        raw = path.read_text("utf-8")
    except OSError:
        raw = ""
    values: dict[str, Any] = {}
    for field in CONFIG_FIELDS:
        key = str(field["key"])
        try:
            value = config_mod.get_value(path, key)
        except KeyError:
            value = effective_value(runtime, key)
        values[key] = jsonable(value)
    return {
        "path": str(path),
        "raw": raw,
        "parsed": jsonable(config_mod.read_raw(path)),
        "fields": [dict(field) for field in CONFIG_FIELDS],
        "values": values,
    }


def set_value(path: Path, key: str, value: Any) -> None:
    config_mod.set_value(path, key, value)


def unset_value(path: Path, key: str) -> bool:
    return config_mod.unset_value(path, key)


def save_raw(path: Path, raw: str) -> None:
    try:
        tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise ControlError(f"TOML 校验失败：{exc}") from exc
    paths_mod.write_atomic(path, raw.rstrip() + "\n")


def effective_value(runtime: Runtime, key: str) -> Any:
    """没有显式配置项时给 UI 一个有效默认值。"""
    parts = key.split(".")
    if parts[0] == "launcher":
        return getattr(runtime.config.launcher, ".".join(parts[1:]), None)
    if parts[0] == "ui":
        if parts[1:2] == ["window"]:
            return getattr(runtime.config.ui.window, ".".join(parts[2:]), None)
        return getattr(runtime.config.ui, parts[1], None)
    try:
        context = runtime.context(parts[0])
    except Exception:  # noqa: BLE001 - 配置错误由服务错误占位展示
        return None
    return getattr(context.settings, ".".join(parts[1:]), None)


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


__all__ = ["CONFIG_FIELDS", "effective_value", "jsonable", "save_raw", "set_value", "snapshot", "unset_value"]
