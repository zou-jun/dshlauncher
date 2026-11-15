"""命令行入口：python -m dshlauncher <command>。"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import traceback
import unicodedata
from pathlib import Path

from . import __version__, actions, install, paths, platform
from . import settings as settings_mod
from .context import Context


def display_width(text: str) -> int:
    """终端显示宽度：中日韩全角字符占两列。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _attach_parent_console() -> None:
    """窗口化 exe 从终端启动时接管父进程控制台，让 print 有地方可写。

    双击时父进程是资源管理器，没有控制台，AttachConsole 失败后保持无窗口启动。
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


def _console_utf8() -> bool:
    """当前 Windows 控制台的输出代码页是不是 65001（UTF-8）。"""
    try:
        import ctypes

        return ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
    except (AttributeError, OSError):  # 非 Windows 或没有控制台
        return False


def _utf8_streams() -> None:
    """让输出编码跟随终端，而不是无条件改成 UTF-8。

    - 用户显式设置了 PYTHONIOENCODING / PYTHONUTF8：一律尊重，不动；
    - Windows 传统代码页（936 等）：保持 Python 默认编码，中文才不会被控制台
      按 GBK 解读成乱码；
    - 控制台是 65001 或非 Windows：统一 UTF-8（POSIX 终端没有代码页问题）。
    """
    if os.environ.get("PYTHONIOENCODING") or os.environ.get("PYTHONUTF8"):
        return
    if sys.platform == "win32" and not _console_utf8():
        return
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


def _gui_error(text: str) -> None:
    """没有控制台时的错误出口：交给平台后端弹原生错误框 / 紧急通知。"""
    with contextlib.suppress(Exception):
        platform.load().message("dshlauncher", text, error=True)


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
    _gui_error(text)


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


def _context(args: argparse.Namespace) -> Context:
    return Context.create(_settings(args))


def _cmd_open(args: argparse.Namespace) -> int:
    _emit("open: " + actions.open_dsh(_context(args)))
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    controller = _context(args).service()
    state = controller.start()
    _audit(f"start: pid={state.pid}")
    _emit(controller.describe())
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    stopped = _context(args).service().stop()
    _emit("已停止服务" if stopped else "服务未在运行")
    return 0


def _cmd_restart(args: argparse.Namespace) -> int:
    context = _context(args)
    _audit("restart: " + actions.restart(context))
    _emit(context.service().describe())
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    snapshot = _context(args).service().status(check_owner=True)
    if getattr(args, "json", False):
        _emit(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2))
    else:
        _emit(snapshot.full())
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from . import doctor

    rows = doctor.report(_context(args))
    if getattr(args, "json", False):
        payload = [{"name": label, "value": value} for label, value in rows]
        _emit(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    width = max(display_width(label) for label, _ in rows)
    _emit("\n".join(f"{pad(label, width)} : {value}" for label, value in rows))
    return 0


def _cmd_tray(args: argparse.Namespace) -> int:
    from . import tray

    context = _context(args)
    return tray.run(context.settings, context=context)


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
    "tray": _cmd_tray,
    "install": _cmd_install,
    "uninstall": _cmd_uninstall,
    "version": _cmd_version,
}


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="服务绑定地址（默认 127.0.0.1）")
    parser.add_argument(
        "--port",
        type=int,
        help="服务端口（默认 3080；该端口被系统保留或被占用时自动回退到 18080 起；0 = 交给系统分配）",
    )
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
        ("tray", "启动系统托盘（双击 exe 时的行为）"),
        ("uninstall", "删除桌面入口"),
        ("version", "打印版本"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        _add_common(sub)
        if name in {"status", "doctor"}:
            sub.add_argument("--json", action="store_true", help="以 JSON 输出")
        sub.set_defaults(handler=HANDLERS[name])

    install_parser = subparsers.add_parser("install", help="创建桌面入口")
    _add_common(install_parser)
    install_parser.add_argument("--icon", help="自定义图标文件")
    install_parser.set_defaults(handler=_cmd_install)

    return parser


def main(argv: list[str] | None = None) -> int:
    _attach_parent_console()
    _utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        # 直接双击 exe：打开窗口并常驻托盘。
        args = parser.parse_args(["tray"])
    try:
        return args.handler(args)
    except Exception as exc:  # noqa: BLE001 - 统一转成提示 + 退出码
        paths.audit(f"{args.command} 失败: {type(exc).__name__}: {exc}", detail=traceback.format_exc())
        _report_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
