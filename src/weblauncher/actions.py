"""对外动作：打开窗口、重启服务（CLI 与托盘共用）。"""

from __future__ import annotations

from . import browser
from .context import ServiceContext
from .splash import SplashServer


def open_service(context: ServiceContext) -> str:
    """确保服务在跑并打开/置前 UI；慢启动的服务先开本地过场页。"""
    controller = context.service()
    state = controller.read_state()
    live = state is not None and controller.live_process(state) is not None
    if live and state is not None:
        url = state.url or controller.latest_url()
        if url:
            result = browser.launch(context.settings, url, backend=context.backend)
            return f"pid={state.pid} started=False window={result}"

    if not context.spec.use_splash:
        state, started = controller.ensure()
        url = state.url or controller.latest_url()
        if not url:
            raise RuntimeError(
                f"服务已启动但没有可用的 URL，请查看日志：{context.paths.service(context.service_id).log}"
            )
        window = browser.launch(context.settings, url, backend=context.backend)
        return f"pid={state.pid} started={started} window={window}"

    splash = SplashServer(title=context.spec.label)
    splash.start()
    try:
        window = browser.launch(
            context.settings,
            splash.url,
            backend=context.backend,
            dedupe=False,
        )
    except Exception:
        splash.close()
        raise

    delay = 30.0
    try:
        state, started = controller.ensure()
        url = state.url or controller.latest_url()
        if not url:
            raise RuntimeError(
                f"服务已启动但日志里没有 URL，请查看日志：{context.paths.service(context.service_id).log}"
            )
        splash.ready(url)
        delivered = splash.wait_delivered(10.0)
        delay = 1.0 if delivered else 30.0
        return f"pid={state.pid} started={started} window={window}"
    except Exception as exc:
        splash.fail(f"{type(exc).__name__}: {exc}")
        delay = 30.0
        raise
    finally:
        splash.close_later(delay)


def restart(context: ServiceContext) -> str:
    controller = context.service()
    controller.stop()
    state = controller.start()
    return f"pid={state.pid}"
