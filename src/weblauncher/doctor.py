"""``doctor`` 的诊断快照：全局环境 + 每个服务的依赖与端口。"""

from __future__ import annotations

import os
import sys

from . import __version__, discovery, ports
from .context import Runtime


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


def _tray_process_text(paths_) -> str:  # noqa: ANN001
    from . import tray

    found = tray.running(paths_)
    if found is None:
        return "未运行"
    return f"运行中 pid={found[0]}，IPC 127.0.0.1:{found[1]}"


def _port_text(controller, settings) -> str:  # noqa: ANN001
    verdict = ports.probe(settings.host, settings.port)
    text = f"{settings.host}:{settings.port}  {verdict.describe()}"
    planned = controller.effective_port()
    if planned == settings.port:
        return text
    state = controller.read_state()
    live = state is not None and state.port == planned and controller.live_process(state) is not None
    suffix = "LISTENING" if live else ports.probe(settings.host, planned).describe()
    return f"{text}  → 自动改用 {settings.host}:{planned}（{suffix}）"


def report(
    runtime: Runtime,
    service_ids: tuple[str, ...] | list[str] | None = None,
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [
        ("启动器", f"{__version__}  ({'frozen' if getattr(sys, 'frozen', False) else 'source'})"),
        ("平台", f"{sys.platform} / backend {getattr(runtime.backend, '__name__', '?').rsplit('.', 1)[-1]}"),
        ("会话", _session_text()),
        ("窗口控制", _window_control_text(runtime.backend, runtime.config.ui.ozone)),
        ("托盘", _tray_text()),
        ("控制台 Agent", _tray_process_text(runtime.paths)),
        ("Python", f"{sys.version.split()[0]}  {sys.executable}"),
        ("数据目录", str(runtime.paths.data)),
        (
            "配置文件",
            f"{runtime.paths.config}  "
            f"({'存在' if runtime.paths.config.is_file() else '不存在，全部走默认值'})",
        ),
        (
            "记忆文件",
            f"{runtime.paths.memory}  ({'存在' if runtime.paths.memory.is_file() else '不存在'})",
        ),
        ("浏览器", _browser_text(runtime)),
    ]
    from .services import registry

    wanted = tuple(service_ids) if service_ids is not None else registry.ids()
    for service_id in wanted:
        try:
            context = runtime.context(service_id)
        except Exception as exc:  # noqa: BLE001 - 单个服务配置失败不能拖垮整张表
            rows.append((f"{service_id} · 配置", f"不可用: {exc}"))
            continue
        prefix = context.spec.id
        controller = context.service()
        settings = context.settings
        rows.append((f"{prefix} · 端口", _port_text(controller, settings)))
        try:
            adapter_rows = context.adapter.doctor_rows()
        except Exception as exc:  # noqa: BLE001 - 依赖缺失时仍展示其余诊断
            rows.append((f"{prefix} · 依赖", f"不可用: {exc}"))
        else:
            for label, value in adapter_rows:
                rows.append((f"{prefix} · {label}", value))
        snapshot = controller.status(check_owner=True)
        pid_text = snapshot.pid if snapshot.pid is not None else "-"
        rows.append((f"{prefix} · 服务", f"{'运行中' if snapshot.running else '未运行'}, pid={pid_text}"))
        rows.append((f"{prefix} · 监听", "LISTENING" if snapshot.listening else "closed"))
        if not snapshot.running and snapshot.listening:
            rows.append((f"{prefix} · 占用者", snapshot.owner or "未知"))
        rows.append(
            (
                f"{prefix} · 状态文件",
                f"{context.paths.service(service_id).state}  ({'有' if controller.read_state() else '无'})",
            )
        )
        rows.append((f"{prefix} · 日志", str(context.paths.service(service_id).log)))
    return rows


def _browser_text(runtime: Runtime) -> str:
    try:
        found = discovery.browser_exe(runtime.config.ui.browser)
    except Exception as exc:  # noqa: BLE001 - doctor 逐项展示失败
        return f"不可用: {exc}"
    return f"{found.family} {found.version or '?'}  {found.path}"
