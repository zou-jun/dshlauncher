"""对外动作：打开窗口、重启服务（CLI 与托盘共用）。"""

from __future__ import annotations

from . import browser
from .context import Context


def open_dsh(context: Context) -> str:
    controller = context.service()
    state, started = controller.ensure()
    url = state.url or controller.latest_url()
    if not url:
        raise RuntimeError("服务已启动但日志里没有 token URL，请查看日志：" + str(context.paths.log))
    result = browser.launch(context.settings, url, backend=context.backend)
    return f"pid={state.pid} started={started} window={result}"


def restart(context: Context) -> str:
    controller = context.service()
    controller.stop()
    state = controller.start()
    return f"pid={state.pid}"
