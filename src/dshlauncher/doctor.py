"""`doctor` 的诊断快照：只收集数据，格式化留给 CLI。"""

from __future__ import annotations

import os
import sys

from . import __version__, discovery, ports, service
from .context import Context
from .paths import Paths


def _session_text() -> str:
    if not sys.platform.startswith("linux"):
        return sys.platform
    session = os.environ.get("XDG_SESSION_TYPE") or "?"
    return (
        f"{session}  WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY') or '-'}"
        f"  DISPLAY={os.environ.get('DISPLAY') or '-'}"
    )


def _window_control_text(backend, ozone: str) -> str:  # noqa: ANN001 - 平台后端模块
    if backend.supports_window_control(ozone):
        return "可用（可枚举 / 置前 / 纠正尺寸）"
    if sys.platform.startswith("linux"):
        return "不可用（原生 Wayland；用 --ozone x11 可启用置前与尺寸纠正）"
    return "不可用"


def _tray_text() -> str:
    try:
        import pystray

        backend = pystray.Icon.__module__.rsplit(".", 1)[-1]
        from .tray import icon_image

        image = icon_image()
    except Exception as exc:  # noqa: BLE001 - doctor 要展示具体原因
        return f"不可用: {exc}"
    return f"可用（后端 {backend}，图标 {image.width}×{image.height}）"


def _tray_process_text(paths_: Paths) -> str:
    from . import tray

    found = tray.running(paths_)
    if found is None:
        return "未运行"
    return f"运行中 pid={found[0]}，IPC 127.0.0.1:{found[1]}"


def _port_text(controller: service.Service, settings) -> str:  # noqa: ANN001 - Settings
    """端口能否 bind；默认端口不可用时一并给出会自动落到哪个端口。"""
    verdict = ports.probe(settings.host, settings.port)
    text = f"{settings.host}:{settings.port}  {verdict.describe()}"
    planned = controller.effective_port()
    if planned == settings.port:
        return text
    state = controller.read_state()
    live = state is not None and state.port == planned and controller.live_process(state) is not None
    suffix = "LISTENING" if live else ports.probe(settings.host, planned).describe()
    return f"{text}  → 自动改用 {settings.host}:{planned}（{suffix}）"


def report(context: Context) -> list[tuple[str, str]]:
    settings = context.settings
    backend = context.backend
    controller = context.service()
    config = context.paths.config

    rows: list[tuple[str, str]] = [
        ("dshlauncher", f"{__version__}  ({'frozen' if getattr(sys, 'frozen', False) else 'source'})"),
        ("平台", f"{sys.platform} / backend {backend.__name__.rsplit('.', 1)[-1]}"),
        ("会话", _session_text()),
        ("窗口控制", _window_control_text(backend, settings.ozone)),
        ("托盘", _tray_text()),
        ("托盘进程", _tray_process_text(context.paths)),
        ("Python", f"{sys.version.split()[0]}  {sys.executable}"),
        ("数据目录", str(context.paths.data)),
        ("配置文件", f"{config}  ({'存在' if config.is_file() else '不存在，全部走默认值'})"),
        ("工作目录", str(settings.work_dir)),
        ("端口", _port_text(controller, settings)),
    ]
    for label, resolver in (
        ("node", lambda: str(discovery.node_exe(settings.node))),
        ("dsh", lambda: str(discovery.dsh_bin(settings.dsh_bin))),
        (
            "浏览器",
            lambda: (lambda found: f"{found.family} {found.version or '?'}  {found.path}")(
                discovery.browser_exe(settings.browser)
            ),
        ),
    ):
        try:
            rows.append((label, resolver()))
        except Exception as exc:  # noqa: BLE001 - doctor 要把每项失败都展示出来
            rows.append((label, f"不可用: {exc}"))

    state = controller.read_state()
    snapshot = controller.status(check_owner=True)
    pid_text = snapshot.pid if snapshot.pid is not None else "-"
    rows.append(("服务", f"{'运行中' if snapshot.running else '未运行'}, pid={pid_text}"))
    rows.append(("监听", "LISTENING" if snapshot.listening else "closed"))
    if not snapshot.running and snapshot.listening:
        rows.append(("占用者", snapshot.owner or "未知"))
    rows.append(("状态文件", f"{context.paths.state}  ({'有' if state else '无'})"))
    rows.append(("日志", str(context.paths.log)))
    return rows
