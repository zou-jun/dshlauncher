"""命令行入口：python -m weblauncher <全局命令> 或 <服务> <命令>。"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import traceback
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__, actions, config, doctor, install, logs, memory, paths, platform, tray
from .context import Runtime, ServiceContext
from .services import registry
from .services.jupyter import kernels as jupyter_kernels
from .services.jupyter import operations as jupyter_operations
from .services.jupyter import workdirs as jupyter_workdirs


def display_width(text: str) -> int:
    """终端显示宽度：中日韩全角字符占两列。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def _attach_parent_console() -> None:
    """窗口化 exe 从终端启动时接管父进程控制台，让 print 有地方可写。"""
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ATTACH_PARENT_PROCESS = -1
    if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
        return
    try:
        # 不强制 UTF-8：让编码跟随控制台代码页，_utf8_streams() 再按需切换。
        sys.stdout = open("CONOUT$", "w", buffering=1, errors="replace")  # noqa: SIM115
        sys.stderr = open("CONOUT$", "w", buffering=1, errors="replace")  # noqa: SIM115
    except OSError:
        pass


def _console_utf8() -> bool:
    try:
        import ctypes

        return ctypes.windll.kernel32.GetConsoleOutputCP() == 65001
    except (AttributeError, OSError):
        return False


def _utf8_streams() -> None:
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
    if sys.stdout is not None:
        with contextlib.suppress(OSError):
            print(text)
    _audit(logs.redact(text))


def _gui_error(text: str) -> None:
    with contextlib.suppress(Exception):
        platform.load().message("weblauncher", text, error=True)


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


# ── 选项 → 服务设置 ───────────────────────────────────────────────────
def _dedupe(args: argparse.Namespace) -> bool | None:
    return False if getattr(args, "no_dedupe", False) else None


def _cli_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {}
    for name in ("host", "port", "browser", "ozone", "profile_dir", "start_timeout"):
        value = getattr(args, name, None)
        if value is not None:
            options[name] = value
    if _dedupe(args) is not None:
        options["dedupe"] = _dedupe(args)
    return options


def _dsh_options(args: argparse.Namespace) -> dict[str, Any]:
    options = _cli_options(args)
    for name in ("cwd", "node", "dsh_bin"):
        value = getattr(args, name, None)
        if value is not None:
            options["work_dir" if name == "cwd" else name] = value
    return options


def _jupyter_options(args: argparse.Namespace) -> dict[str, Any]:
    options = _cli_options(args)
    for name in ("root", "kernel", "jupyter_bin", "base_url"):
        value = getattr(args, name, None)
        if value is not None:
            options[name] = value
    return options


def _service_options(args: argparse.Namespace, service_id: str) -> dict[str, Any]:
    return _dsh_options(args) if service_id == "dsh" else _jupyter_options(args)


def _runtime() -> Runtime:
    return Runtime.create()


def _service_ids(value: str) -> tuple[str, ...]:
    return registry.split(value)


# ── 全局命令 ──────────────────────────────────────────────────────────
def _cmd_start(args: argparse.Namespace) -> int:
    failures = 0
    runtime = _runtime()
    for service_id in _service_ids(args.service):
        try:
            context = runtime.context(service_id, _service_options(args, service_id))
            state = context.service().start()
            _audit(f"start {service_id}: pid={state.pid} port={state.port}")
            _emit(f"[{context.spec.label}]")
            _emit(context.service().describe())
        except Exception as exc:  # noqa: BLE001 - 批量启动逐个汇报
            failures += 1
            _report_error(exc)
    return 1 if failures else 0


def _cmd_stop(args: argparse.Namespace) -> int:
    failures = 0
    runtime = _runtime()
    for service_id in _service_ids(args.service):
        try:
            context = runtime.context(service_id, _service_options(args, service_id))
            stopped = context.service().stop(force=getattr(args, "force", False))
            _emit(f"[{context.spec.label}] " + ("已停止服务" if stopped else "服务未在运行"))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _report_error(exc)
    return 1 if failures else 0


def _cmd_restart(args: argparse.Namespace) -> int:
    failures = 0
    runtime = _runtime()
    for service_id in _service_ids(args.service):
        try:
            context = runtime.context(service_id, _service_options(args, service_id))
            _audit(f"restart {service_id}: " + actions.restart(context))
            _emit(f"[{context.spec.label}]")
            _emit(context.service().describe())
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _report_error(exc)
    return 1 if failures else 0


def _cmd_open(args: argparse.Namespace) -> int:
    failures = 0
    runtime = _runtime()
    for service_id in _service_ids(args.service):
        try:
            context = runtime.context(service_id, _service_options(args, service_id))
            _emit(f"[{context.spec.label}] open: " + actions.open_service(context))
        except Exception as exc:  # noqa: BLE001
            failures += 1
            _report_error(exc)
    return 1 if failures else 0


def _cmd_status(args: argparse.Namespace) -> int:
    runtime = _runtime()
    wanted = registry.split(args.service)
    snapshots = []
    errors: list[tuple[str, str]] = []
    for service_id in wanted:
        try:
            context = runtime.context(service_id, _service_options(args, service_id))
        except Exception as exc:  # noqa: BLE001 - 一个服务没装好不影响其它服务
            errors.append((service_id, f"{type(exc).__name__}: {exc}"))
            continue
        snapshots.append((context, context.service().status(check_owner=True)))

    if args.json:
        if len(wanted) == 1 and snapshots:
            _emit(json.dumps(snapshots[0][1].as_dict(), ensure_ascii=False, indent=2))
        else:
            payload = {context.service_id: snapshot.as_dict() for context, snapshot in snapshots}
            for service_id, error in errors:
                payload[service_id] = {"error": error, "running": False}
            _emit(json.dumps({"services": payload}, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    for index, (context, snapshot) in enumerate(snapshots):
        if index:
            _emit("")
        _emit(f"[{context.spec.label}]")
        _emit(snapshot.full())
    for service_id, error in errors:
        if snapshots:
            _emit("")
        _emit(f"[{service_id}] 不可用: {error}")
    return 1 if errors else 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    runtime = _runtime()
    rows = doctor.report(runtime, registry.split(args.service))
    if args.json:
        payload = [{"name": label, "value": value} for label, value in rows]
        _emit(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    width = max(display_width(label) for label, _ in rows)
    _emit("\n".join(f"{pad(label, width)} : {value}" for label, value in rows))
    return 0


def _cmd_tray(args: argparse.Namespace) -> int:
    return tray.run(_runtime())


def _cmd_ui(args: argparse.Namespace) -> int:
    target = "/#/"
    if getattr(args, "service", None):
        target = f"/#/services/{args.service}"
    return tray.run(_runtime(), target=target)


def _cmd_install(args: argparse.Namespace) -> int:
    created = install.create(
        Path(args.icon).expanduser() if args.icon else None,
        services=registry.split(args.service) if args.service else registry.ids(),
    )
    _emit("\n".join(f"已创建: {path}" for path in created))
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    removed = install.remove()
    _emit("\n".join(f"已删除: {path}" for path in removed) if removed else "没有找到启动器的入口")
    return 0


def _cmd_version(args: argparse.Namespace) -> int:
    _emit(__version__)
    return 0


# ── config ────────────────────────────────────────────────────────────
def _cmd_config(args: argparse.Namespace) -> int:
    path = paths.config_path()
    if args.config_command == "path":
        _emit(str(path))
        return 0
    if args.config_command == "list":
        try:
            text = path.read_text("utf-8").strip()
        except OSError:
            text = ""
        _emit(text if text else "（配置文件为空，全部走默认值）")
        return 0
    if args.config_command == "get":
        try:
            value = config.get_value(path, args.key)
        except KeyError:
            raise SystemExit(f"没有配置项 {args.key}") from None
        _emit(json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value)
        return 0
    if args.config_command == "set":
        before = path.read_text("utf-8") if path.is_file() else ""
        try:
            config.set_value(path, args.key, config.parse_value(args.value))
            import tomllib

            tomllib.loads(path.read_text("utf-8"))
        except Exception:
            if before:
                path.write_text(before, "utf-8")
            else:
                path.unlink(missing_ok=True)
            raise
        _emit(f"{args.key} = {config.format_value(config.parse_value(args.value))}")
        return 0
    if args.config_command == "unset":
        removed = config.unset_value(path, args.key)
        _emit(f"已删除 {args.key}" if removed else f"没有配置项 {args.key}")
        return 0
    return 2


# ── dsh 专属命令 ──────────────────────────────────────────────────────
def _dsh_context(args: argparse.Namespace) -> ServiceContext:
    runtime = _runtime()
    return runtime.context("dsh", _dsh_options(args))


def _cmd_dsh_updates(args: argparse.Namespace) -> int:
    from .services.dsh import updates

    runtime = _runtime()
    context = runtime.context("dsh", _dsh_options(args))
    if args.panel:
        target = f"/#/services/dsh/updates?profile={quote(args.profile)}&timeout={quote(str(args.timeout))}"
        try:
            url = tray.send_ui(
                runtime.paths,
                timeout=5.0,
                target=target,
            )
        except tray.TrayUnavailable:
            return tray.run(runtime, target=target)
        tray.open_console_url(runtime, url)
        return 0
    report = updates.check(context.settings, profile=args.profile, timeout=args.timeout)
    if args.json:
        _emit(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        _emit(updates.format_report(report))
    if report.update_count:
        return 1
    return 2 if report.errors else 0


# ── jupyter 专属命令 ──────────────────────────────────────────────────
def _save_memory(runtime: Runtime) -> None:
    memory.save(runtime.memory, runtime.paths.memory)


def _kernel_flag(context: ServiceContext, name: str) -> str:
    return "*" if getattr(context.settings, "kernel", None) == name else " "


def _cmd_jupyter_kernel(args: argparse.Namespace) -> int:
    runtime = _runtime()
    context = runtime.context("jupyter", _jupyter_options(args))
    install = context.adapter.install
    command = args.kernel_command

    if command == "list":
        specs = jupyter_kernels.list_kernels(install, runtime.memory)
        if args.json:
            _emit(json.dumps([spec.as_dict() for spec in specs], ensure_ascii=False, indent=2))
            return 0
        if not specs:
            _emit("（没有已安装的内核）")
            return 0
        rows = [("默认", "名称", "显示名", "Python", "说明")]
        for spec in specs:
            note = "启动器注册" if spec.managed else ""
            if spec.broken:
                note = (note + "；解释器不存在").strip("；")
            rows.append(
                (
                    _kernel_flag(context, spec.name),
                    spec.name,
                    spec.display_name,
                    spec.python or "-",
                    note or "-",
                )
            )
        widths = [max(display_width(row[index]) for row in rows) for index in range(4)]
        for index, row in enumerate(rows):
            _emit("  ".join(pad(row[column], widths[column]) for column in range(4)) + "  " + row[4])
            if index == 0:
                _emit("")
        return 0

    if command == "add":
        spec = jupyter_operations.add_kernel(
            install,
            runtime.memory,
            directory=args.dir,
            python=args.python,
            name=args.name,
            display_name=args.display_name,
            replace=args.replace,
            install_dependency=args.install_ipykernel,
        )
        _save_memory(runtime)
        if args.json:
            _emit(json.dumps(spec.as_dict(), ensure_ascii=False, indent=2))
        else:
            _emit(f"已注册内核 {spec.name}（{spec.display_name}）\n  {spec.resource_dir}")
        return 0

    if command == "show":
        spec = jupyter_kernels.require_found(install, runtime.memory, args.name)
        data = spec.as_dict()
        data["default"] = _kernel_flag(context, spec.name) == "*"
        _emit(
            json.dumps(data, ensure_ascii=False, indent=2)
            if args.json
            else "\n".join(f"{key}: {value}" for key, value in data.items())
        )
        return 0

    if command == "use":
        spec = jupyter_operations.select_kernel(
            install,
            runtime.memory,
            args.name,
            workdir=context.settings.root_dir,
        )
        _save_memory(runtime)
        _emit(f"默认内核已设为 {spec.name}（{spec.display_name}）；运行中的服务需要 restart 后生效")
        return 0

    if command == "rename":
        spec = jupyter_kernels.require_found(install, runtime.memory, args.name)
        if not args.display_name:
            raise SystemExit("rename 目前只支持 --display-name（改内核 ID 会让已有 notebook 找不到内核）")
        renamed = jupyter_kernels.rename_kernel(spec, args.display_name)
        _emit(f"{renamed.name} 显示名已改为 {renamed.display_name}")
        return 0

    if command == "remove":
        spec = jupyter_operations.remove_kernel(
            install,
            runtime.memory,
            args.name,
            force=args.force,
        )
        _save_memory(runtime)
        _emit(f"已删除内核 {spec.name}")
        return 0
    return 2


def _cmd_jupyter_workdir(args: argparse.Namespace) -> int:
    runtime = _runtime()
    command = args.workdir_command

    if command == "list":
        values = jupyter_workdirs.recent(runtime.memory)
        current = memory.get(runtime.memory, "jupyter", "workdir", None)
        if args.json:
            _emit(
                json.dumps(
                    [
                        {"path": str(path), "exists": path.is_dir(), "current": str(path) == str(current)}
                        for path in values
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not values:
            _emit("（还没有记录过工作目录）")
            return 0
        for path in values:
            marker = "*" if str(path) == str(current) else " "
            suffix = "" if path.is_dir() else "  （不存在）"
            _emit(f"{marker} {path}{suffix}")
        return 0

    if command == "current":
        context = runtime.context("jupyter", _jupyter_options(args))
        _emit(str(context.settings.root_dir))
        return 0

    if command == "use":
        kernel = args.kernel
        context = runtime.context("jupyter", _jupyter_options(args))
        install = context.adapter.install if kernel else None
        workdir = jupyter_operations.select_workdir(
            install,
            runtime.memory,
            args.path,
            kernel=kernel,
        )
        _save_memory(runtime)
        _emit(f"工作目录已设为 {workdir}")
        try:
            context = runtime.context("jupyter", _jupyter_options(args))
            state = context.service().read_state()
            snapshot = context.service().status(check_ports=False)
            if snapshot.running and state is not None:
                recorded = state.extra.get("root_dir") if isinstance(state.extra, dict) else None
                if recorded and Path(recorded).expanduser().resolve() != workdir:
                    _emit("Jupyter 正在运行，root_dir 需要 restart 后生效")
        except Exception:
            pass
        return 0
    return 2


# ── 解析器 ────────────────────────────────────────────────────────────
def _add_common(parser: argparse.ArgumentParser, *, root: bool = True) -> None:
    parser.add_argument("--host", help="服务绑定地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, help="服务端口（0 = 交给系统分配）")
    parser.add_argument("--browser", help="chrome / edge / chromium / brave，或浏览器可执行文件路径")
    parser.add_argument("--ozone", choices=config.OZONE_MODES, help="Linux 上 Chrome 的显示后端")
    parser.add_argument("--profile-dir", dest="profile_dir", help="专用浏览器配置目录")
    parser.add_argument("--no-dedupe", action="store_true", help="已有窗口时也强制新开一个")
    parser.add_argument("--start-timeout", type=float, dest="start_timeout", help="等服务就绪的秒数")
    parser.add_argument("--cwd", help="工作目录")
    if root:
        parser.add_argument("--root", help="工作目录（Jupyter root_dir）")


def _add_service_options(parser: argparse.ArgumentParser) -> None:
    _add_common(parser, root=False)
    parser.add_argument("--node", help="node 可执行文件路径")
    parser.add_argument("--dsh-bin", dest="dsh_bin", help="dsh 的 lib/bin.js 路径")
    parser.add_argument("--root", help="Jupyter 工作目录（root_dir）")
    parser.add_argument("--kernel", help="Jupyter 默认内核（kernelspec id）")
    parser.add_argument("--jupyter-bin", dest="jupyter_bin", help="jupyter-lab 可执行文件路径")
    parser.add_argument("--base-url", dest="base_url", help="Jupyter base_url（默认 /）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="weblauncher",
        description="托管 dsh web / Jupyter Lab 等本地服务",
    )
    sub = parser.add_subparsers(dest="command")

    tray_parser = sub.add_parser("tray", help="常驻控制台 Agent（兼容入口）")
    tray_parser.set_defaults(handler=_cmd_tray)

    ui_parser = sub.add_parser("ui", help="打开 Web 控制台（双击 exe 的默认行为）")
    ui_parser.add_argument("service", nargs="?", help="可选：打开某个服务详情")
    ui_parser.set_defaults(handler=_cmd_ui)

    for name, help_text in (
        ("start", "启动一个服务（dsh / jupyter / all）"),
        ("stop", "停止一个服务"),
        ("restart", "重启一个服务"),
        ("open", "确保服务在跑并打开 UI"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("service", help="dsh / jupyter / all")
        _add_service_options(command)
        if name == "stop":
            command.add_argument("--force", action="store_true", help="允许清理无 state 记录的同类进程")
        command.set_defaults(
            handler={
                "start": _cmd_start,
                "stop": _cmd_stop,
                "restart": _cmd_restart,
                "open": _cmd_open,
            }[name]
        )

    status = sub.add_parser("status", help="查看服务状态")
    status.add_argument("service", nargs="?", default="all", help="dsh / jupyter / all（默认 all）")
    _add_service_options(status)
    status.add_argument("--json", action="store_true", help="以 JSON 输出")
    status.set_defaults(handler=_cmd_status)

    doctor_parser = sub.add_parser("doctor", help="依赖、端口与运行时诊断")
    doctor_parser.add_argument("service", nargs="?", default="all", help="dsh / jupyter / all")
    doctor_parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    doctor_parser.set_defaults(handler=_cmd_doctor)

    config_parser = sub.add_parser("config", help="读写 config.toml")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("list", help="打印配置文件").set_defaults(handler=_cmd_config)
    get_parser = config_sub.add_parser("get", help="读取一个配置项")
    get_parser.add_argument("key", help="如 dsh.port / ui.browser")
    get_parser.set_defaults(handler=_cmd_config)
    set_parser = config_sub.add_parser("set", help="写入一个配置项")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.set_defaults(handler=_cmd_config)
    unset_parser = config_sub.add_parser("unset", help="删除一个配置项")
    unset_parser.add_argument("key")
    unset_parser.set_defaults(handler=_cmd_config)
    config_sub.add_parser("path", help="打印配置文件路径").set_defaults(handler=_cmd_config)

    install_parser = sub.add_parser("install", help="创建桌面入口")
    install_parser.add_argument("--service", help="dsh / jupyter / all（默认全部）")
    install_parser.add_argument("--icon", help="自定义图标文件")
    install_parser.set_defaults(handler=_cmd_install)

    sub.add_parser("uninstall", help="删除桌面入口").set_defaults(handler=_cmd_uninstall)
    sub.add_parser("version", help="打印版本").set_defaults(handler=_cmd_version)

    dsh = sub.add_parser("dsh", help="dsh 专属命令")
    dsh_sub = dsh.add_subparsers(dest="dsh_command", required=True)
    updates = dsh_sub.add_parser("updates", help="检查 dsh / 插件更新")
    updates.add_argument("--json", action="store_true")
    updates.add_argument("--panel", action="store_true", help="打开可点击升级的本地面板")
    updates.add_argument("--profile", default="web", help="dsh profile（默认 web）")
    updates.add_argument("--timeout", type=float, default=30.0, help="单次查询秒数")
    _add_common(updates, root=False)
    updates.add_argument("--node")
    updates.add_argument("--dsh-bin", dest="dsh_bin")
    updates.set_defaults(handler=_cmd_dsh_updates)

    # 兼容旧入口：weblauncher updates
    legacy = sub.add_parser("updates", help="等同 dsh updates")
    legacy.add_argument("--json", action="store_true")
    legacy.add_argument("--panel", action="store_true")
    legacy.add_argument("--profile", default="web")
    legacy.add_argument("--timeout", type=float, default=30.0)
    _add_common(legacy, root=False)
    legacy.add_argument("--node")
    legacy.add_argument("--dsh-bin", dest="dsh_bin")
    legacy.set_defaults(handler=_cmd_dsh_updates)

    jupyter = sub.add_parser("jupyter", help="Jupyter 专属命令")
    jupyter_sub = jupyter.add_subparsers(dest="jupyter_command", required=True)

    kernel = jupyter_sub.add_parser("kernel", help="内核管理")
    kernel_sub = kernel.add_subparsers(dest="kernel_command", required=True)
    kernel_list = kernel_sub.add_parser("list", help="列出内核")
    kernel_list.add_argument("--json", action="store_true")
    kernel_list.set_defaults(handler=_cmd_jupyter_kernel)
    kernel_add = kernel_sub.add_parser("add", help="注册解释器为内核")
    kernel_add.add_argument("python", nargs="?")
    kernel_add.add_argument("--dir", help="包含 .venv 的项目目录")
    kernel_add.add_argument("--name", help="kernelspec id（默认取目录名）")
    kernel_add.add_argument("--display-name", dest="display_name", help="Jupyter 里显示的名字")
    kernel_add.add_argument("--replace", action="store_true", help="覆盖同名内核")
    kernel_add.add_argument("--install-ipykernel", action="store_true", help="缺 ipykernel 时自动安装")
    kernel_add.add_argument("--json", action="store_true")
    kernel_add.set_defaults(handler=_cmd_jupyter_kernel)
    kernel_show = kernel_sub.add_parser("show", help="查看内核详情")
    kernel_show.add_argument("name")
    kernel_show.add_argument("--json", action="store_true")
    kernel_show.set_defaults(handler=_cmd_jupyter_kernel)
    kernel_use = kernel_sub.add_parser("use", help="设为新 notebook 的默认内核")
    kernel_use.add_argument("name")
    kernel_use.set_defaults(handler=_cmd_jupyter_kernel)
    kernel_rename = kernel_sub.add_parser("rename", help="修改显示名")
    kernel_rename.add_argument("name")
    kernel_rename.add_argument("--display-name", dest="display_name")
    kernel_rename.set_defaults(handler=_cmd_jupyter_kernel)
    kernel_remove = kernel_sub.add_parser("remove", help="删除用户内核")
    kernel_remove.add_argument("name")
    kernel_remove.add_argument("--force", action="store_true", help="允许删除非启动器注册的内核")
    kernel_remove.set_defaults(handler=_cmd_jupyter_kernel)

    workdir = jupyter_sub.add_parser("workdir", help="工作目录记忆", aliases=["dir"])
    workdir_sub = workdir.add_subparsers(dest="workdir_command", required=True)
    workdir_list = workdir_sub.add_parser("list", help="最近目录")
    workdir_list.add_argument("--json", action="store_true")
    workdir_list.set_defaults(handler=_cmd_jupyter_workdir)
    current = workdir_sub.add_parser("current", help="当前目录")
    current.set_defaults(handler=_cmd_jupyter_workdir)
    use = workdir_sub.add_parser("use", help="选择工作目录")
    use.add_argument("path")
    use.add_argument("--kernel", help="同时记录该目录使用的内核")
    use.set_defaults(handler=_cmd_jupyter_workdir)

    return parser


def main(argv: list[str] | None = None) -> int:
    _attach_parent_console()
    _utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["ui"])
    try:
        return args.handler(args)
    except Exception as exc:  # noqa: BLE001 - 统一转成提示 + 退出码
        paths.audit(
            logs.redact(f"{args.command} 失败: {type(exc).__name__}: {exc}"),
            detail=logs.redact(traceback.format_exc()),
        )
        _report_error(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
