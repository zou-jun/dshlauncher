"""对外动作：打开窗口、重启服务（CLI 与托盘共用）。"""

from __future__ import annotations

from . import browser
from .context import ServiceContext
from .tickets import TicketServer


def _open_url(context: ServiceContext, url: str, *, dedupe: bool | None = None) -> str:
    """用一次性 ticket 打开目标 URL，避免服务 token 出现在 Chromium argv。"""
    ticket = TicketServer(url)
    ticket.start()
    try:
        result = browser.launch(
            context.settings,
            ticket.url,
            backend=context.backend,
            dedupe=dedupe,
        )
    except Exception:
        ticket.close()
        raise
    ticket.close_later(15.0)
    return result


def open_service(context: ServiceContext) -> str:
    """确保服务在跑并打开/置前 UI；启动进度显示在控制台。"""
    controller = context.service()
    state = controller.read_state()
    live = state is not None and controller.live_process(state) is not None
    if live and state is not None:
        url = state.url or controller.latest_url()
        if url:
            result = _open_url(context, url)
            return f"pid={state.pid} started=False window={result}"

    state, started = controller.ensure()
    url = state.url or controller.latest_url()
    if not url:
        raise RuntimeError(
            f"服务已启动但没有可用的 URL，请查看日志：{context.paths.service(context.service_id).log}"
        )
    window = _open_url(context, url)
    return f"pid={state.pid} started={started} window={window}"


def restart(context: ServiceContext) -> str:
    controller = context.service()
    state = controller.restart()
    return f"pid={state.pid}"
