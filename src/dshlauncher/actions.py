"""对外动作：打开窗口、重启服务（CLI 与面板共用）。"""

from __future__ import annotations

from . import browser, paths, service
from .settings import Settings


def open_dsh(settings: Settings) -> str:
    controller = service.Service(settings)
    state, started = controller.ensure()
    url = state.url or controller.latest_url()
    if not url:
        raise RuntimeError("服务已启动但日志里没有 token URL，请查看日志：" + str(paths.log_path()))
    result = browser.launch(settings, url)
    return f"pid={state.pid} started={started} window={result}"


def restart(settings: Settings) -> str:
    controller = service.Service(settings)
    controller.stop()
    state = controller.start()
    return f"pid={state.pid}"
