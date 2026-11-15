"""对外动作：打开窗口、重启服务（CLI 与托盘共用）。"""

from __future__ import annotations

from . import browser
from .context import Context
from .splash import SplashServer


def open_dsh(context: Context) -> str:
    controller = context.service()
    state = controller.read_state()
    live = state is not None and controller.live_process(state) is not None
    if live and state is not None:
        url = state.url or controller.latest_url()
        if url:
            result = browser.launch(context.settings, url, backend=context.backend)
            return f"pid={state.pid} started=False window={result}"

    # 服务未就绪：先把窗口开到本地过场页，就绪后由页面自己跳转。
    splash = SplashServer()
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
            raise RuntimeError("服务已启动但日志里没有 token URL，请查看日志：" + str(context.paths.log))
        splash.ready(url)
        delivered = splash.wait_delivered(10.0)
        # 页面还没取到 ready 时多留一会儿：首次启动 Chrome 可能很慢。
        delay = 1.0 if delivered else 30.0
        return f"pid={state.pid} started={started} window={window}"
    except Exception as exc:
        splash.fail(f"{type(exc).__name__}: {exc}")
        delay = 30.0
        raise
    finally:
        splash.close_later(delay)


def restart(context: Context) -> str:
    controller = context.service()
    controller.stop()
    state = controller.start()
    return f"pid={state.pid}"
