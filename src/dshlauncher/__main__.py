"""命令行入口：python -m dshlauncher <command>。"""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import unicodedata
from pathlib import Path

from . import __version__, actions, discovery, install, paths, platform, service
from . import settings as settings_mod


def display_width(text: str) -> int:
    """终端显示宽度：中日韩全角字符占两列。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _attach_parent_console() -> None:
    """窗口化 exe 从终端启动时接管父进程控制台，让 print 有地方可写。

    没有参数（双击）时不接管：保持"无窗口"启动，错误走 MessageBox。
    """
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ATTACH_PARENT_PROCESS = -1
    if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
        return  # 从资源管理器/计划任务启动：没有父控制台
    try:
        # 这两个流要一直用到进程结束，不能放进 with。
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1, errors="replace")  # noqa: SIM115
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1, errors="replace")  # noqa: SIM115
    except OSError:
        pass


def _utf8_streams() -> None:
    """冻结成 exe 后 stdout 会退回 ANSI 代码页，中文会乱码；统一成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def _audit(text: str) -> None:
    paths.audit(text)


def _emit(text: str) -> None:
    """窗口化 exe 没有 stdout；有终端时才打印，同时落审计日志。"""
    if sys.stdout is not None:
        with contextlib.suppress(OSError):
            print(text)
    _audit(text)


def _report_error(exc: BaseException) -> None:
    text = f"{type(exc).__name__}: {exc}"
    if sys.stdout is not None:
        with contextlib.suppress(OSError):
            print(text, file=sys.stderr)
        if not sys.platform.startswith("linux"):
            return
        tty = True
        with contextlib.suppress(Exception):
            tty = sys.stdout.isatty()
        if tty:
            return
    elif not sys.platform.startswith("linux"):
        # Windows 窗口化 exe：没有 stdout，只能用对话框。
        with contextlib.suppress(Exception):
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("dshlauncher", text, parent=root)
            root.destroy()
        return

    # Linux 从 .desktop 启动时没有终端，错误只能走桌面通知。
    with contextlib.suppress(OSError):
        subprocess.run(
            ["notify-send", "--urgency=critical", "dshlauncher", text],
            check=False,
            timeout=5,
        )


def _settings(args: argparse.Namespace) -> settings_mod.Settings:
    return settings_mod.load(
        host=args.host,
        port=args.port,
        work_dir=args.cwd,
        node=args.node,
        dsh_bin=args.dsh_bin,
        browser=args.browser,
        ozone=args.ozone,
        profile_dir=args.profile_dir,
        dedupe=False if args.no_dedupe else None,
        start_timeout=args.start_timeout,
    )


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


def _tk_text() -> str:
    try:
        import tkinter as tk
        from tkinter import font as tkfont

        root = tk.Tk()
        root.withdraw()
    except Exception as exc:  # noqa: BLE001 - doctor 要展示失败原因
        return f"不可用: {exc}"
    try:
        if tkfont.nametofont("TkDefaultFont").measure("窗口") > 0:
            return f"可用 (Tk {tk.TkVersion})"
        return f"Tk {tk.TkVersion} 缺少中文字形（无 Xft），控制面板将使用英文标签"
    finally:
        root.destroy()


def _cmd_open(args: argparse.Namespace) -> int:
    _emit("open: " + actions.open_dsh(_settings(args)))
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    controller = service.Service(_settings(args))
    state = controller.start()
    _audit(f"start: pid={state.pid}")
    _emit(controller.describe())
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    stopped = service.Service(_settings(args)).stop()
    _emit("已停止服务" if stopped else "服务未在运行")
    return 0


def _cmd_restart(args: argparse.Namespace) -> int:
    _audit("restart: " + actions.restart(_settings(args)))
    _emit(service.Service(_settings(args)).describe())
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    _emit(service.Service(_settings(args)).describe())
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    backend = platform.load()
    controller = service.Service(settings)
    config = paths.config_path()

    rows: list[tuple[str, str]] = [
        ("dshlauncher", f"{__version__}  ({'frozen' if getattr(sys, 'frozen', False) else 'source'})"),
        ("平台", f"{sys.platform} / backend {backend.__name__.rsplit('.', 1)[-1]}"),
        ("会话", _session_text()),
        ("窗口控制", _window_control_text(backend, settings.ozone)),
        ("tkinter", _tk_text()),
        ("Python", f"{sys.version.split()[0]}  {sys.executable}"),
        ("数据目录", str(paths.data_dir())),
        ("配置文件", f"{config}  ({'存在' if config.is_file() else '不存在，全部走默认值'})"),
        ("工作目录", str(settings.work_dir)),
        ("端口", f"{settings.host}:{settings.port}"),
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
    running = controller.live_process(state) is not None
    listening = controller.port_open()
    pid_text = state.pid if running and state is not None else "-"
    rows.append(("服务", f"{'运行中' if running else '未运行'}, pid={pid_text}"))
    rows.append(("监听", "LISTENING" if listening else "closed"))
    if not running and listening:
        rows.append(("占用者", controller.port_owner() or "未知"))
    rows.append(("状态文件", f"{paths.state_path()}  ({'有' if state else '无'})"))
    rows.append(("日志", str(paths.log_path())))

    width = max(display_width(label) for label, _ in rows)
    _emit("\n".join(f"{pad(label, width)} : {value}" for label, value in rows))
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    from . import ui_panel

    ui_panel.run(_settings(args))
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    created = install.create(Path(args.icon).expanduser() if args.icon else None)
    _emit("\n".join(f"已创建: {path}" for path in created))
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    removed = install.remove()
    _emit("\n".join(f"已删除: {path}" for path in removed) if removed else "没有找到 dshlauncher 的入口")
    return 0


def _cmd_version(args: argparse.Namespace) -> int:
    _emit(__version__)
    return 0


HANDLERS = {
    "open": _cmd_open,
    "start": _cmd_start,
    "stop": _cmd_stop,
    "restart": _cmd_restart,
    "status": _cmd_status,
    "doctor": _cmd_doctor,
    "ui": _cmd_ui,
    "install": _cmd_install,
    "uninstall": _cmd_uninstall,
    "version": _cmd_version,
}


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="服务绑定地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, help="服务端口（默认 3080）")
    parser.add_argument("--cwd", help="服务工作目录（默认系统临时目录）")
    parser.add_argument("--node", help="node 可执行文件路径")
    parser.add_argument("--dsh-bin", dest="dsh_bin", help="dsh 的 lib/bin.js 路径")
    parser.add_argument("--browser", help="chrome / edge / chromium / brave，或浏览器可执行文件路径")
    parser.add_argument(
        "--ozone",
        choices=settings_mod.OZONE_MODES,
        help="Linux 上 Chrome 的显示后端：auto（默认，交给 Chrome） / x11（XWayland，可置前）",
    )
    parser.add_argument("--profile-dir", dest="profile_dir", help="专用浏览器配置目录")
    parser.add_argument("--no-dedupe", action="store_true", help="已有窗口时也强制新开一个")
    parser.add_argument(
        "--start-timeout", type=float, dest="start_timeout", help="等服务就绪的秒数（默认 120）"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dshlauncher",
        description="托管 dsh web 服务，并在无扩展的 Chromium 窗口里打开 UI",
    )
    subparsers = parser.add_subparsers(dest="command")

    for name, help_text in (
        ("open", "确保服务在跑并打开/置前窗口（默认入口）"),
        ("start", "只启动服务"),
        ("stop", "停止服务"),
        ("restart", "重启服务（dsh 升级后执行）"),
        ("status", "查看服务状态"),
        ("doctor", "打印依赖发现结果与运行状态"),
        ("ui", "打开 tkinter 控制面板"),
        ("uninstall", "删除桌面入口"),
        ("version", "打印版本"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        _add_common(sub)
        sub.set_defaults(handler=HANDLERS[name])

    install_parser = subparsers.add_parser("install", help="创建桌面入口")
    _add_common(install_parser)
    install_parser.add_argument("--icon", help="自定义图标文件")
    install_parser.set_defaults(handler=_cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    if sys.argv[1:] if argv is None else argv:
        _attach_parent_console()
    _utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        # 直接双击 exe 时等同于 open。
        args = parser.parse_args(["open"])
    try:
        return args.handler(args)
    except Exception as exc:  # noqa: BLE001 - 统一转成提示 + 退出码
        _audit(f"{args.command} 失败: {type(exc).__name__}: {exc}")
        _report_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
