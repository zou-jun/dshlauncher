"""系统托盘：双击后的常驻形态，右键菜单承载原控制台的全部操作。

进程模型：

- 双击先尝试把「打开窗口」交给已存在的托盘（loopback IPC + token），
  成功则本进程立即退出；
- 没有托盘时用 ``tray.lock`` 抢单实例，抢到就成为托盘，抢不到说明
  另一个实例正在启动，等它就绪后把请求投递过去，再不行才自己打开窗口。

托盘「退出并停止服务」按约定停掉 dsh 服务；浏览器窗口留在原地。
"""

from __future__ import annotations

import contextlib
import hmac
import json
import os
import secrets
import socket
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from . import actions, paths, platform, service
from .settings import Settings

TITLE = "DeepSeek Harness"
ICON_SIZE = 64
LOCK_NAME = "tray.lock"
INFO_NAME = "tray.json"
START_WAIT = 30.0
CONNECT_TIMEOUT = 5.0
TITLE_INTERVAL = 2.0
BUSY_TEXT = "有操作正在进行，请稍后再试"


class TrayUnavailable(RuntimeError):
    """没有可用的托盘进程（未启动、已退出或信息文件损坏）。"""


# ── 状态文本 ──────────────────────────────────────────────────────────
def status_text(controller: service.Service) -> str:
    state = controller.read_state()
    proc = controller.live_process(state)
    if state is None or proc is None:
        return "未运行"
    return f"运行中 · pid={proc.pid} · {controller.settings.host}:{state.port}"


def state_text(controller: service.Service) -> str:
    """菜单里的短状态；完整信息点开后由 ``describe`` 提供。"""
    state = controller.read_state()
    if state is None or controller.live_process(state) is None:
        return "未运行"
    return "运行中"


# ── 图标 ──────────────────────────────────────────────────────────────
def _icon_candidates() -> list[Path]:
    candidates: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidates.append(Path(bundle) / "assets" / "app.png")
    root = paths.executable_dir()
    candidates.append(root / "assets" / "app.png")
    candidates.append(root / "packaging" / "assets" / "app.png")
    candidates.append(Path(__file__).resolve().parents[2] / "packaging" / "assets" / "app.png")
    return candidates


def icon_image() -> Any:
    """托盘图标（PIL Image）；找不到图片时抛错，由调用方提示。"""
    from PIL import Image

    for candidate in _icon_candidates():
        try:
            with Image.open(candidate) as image:
                return image.convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.Resampling.LANCZOS)
        except OSError:
            continue
    raise RuntimeError("找不到托盘图标：assets/app.png")


# ── 单实例锁 ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Lock:
    path: Path
    pid: int
    create_time: float


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _alive(pid: int, create_time: float) -> bool:
    """pid 存在且启动时间一致（防 PID 复用）。"""
    try:
        proc = psutil.Process(pid)
        return abs(proc.create_time() - create_time) < 1.0
    except (psutil.Error, OSError):
        return False


def _holder(path: Path) -> tuple[int, float] | None:
    data = _read_json(path)
    if data is None:
        return None
    try:
        return int(data["pid"]), float(data["create_time"])
    except (KeyError, TypeError, ValueError):
        return None


def _fresh(path: Path, seconds: float = 5.0) -> bool:
    """锁文件刚创建、内容还没写完：保守地当作有人在抢。"""
    try:
        return time.time() - path.stat().st_mtime < seconds
    except OSError:
        return False


def acquire_lock() -> Lock | None:
    """抢到返回 Lock；已有活着的托盘（或正在写锁）返回 None。"""
    path = paths.ensure_data_dir() / LOCK_NAME
    for _ in range(5):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            holder = _holder(path)
            if holder is not None and _alive(*holder):
                return None
            if holder is None and _fresh(path):
                return None
            path.unlink(missing_ok=True)
            continue
        try:
            pid = os.getpid()
            create_time = psutil.Process().create_time()
            os.write(fd, json.dumps({"pid": pid, "create_time": create_time}).encode())
        finally:
            os.close(fd)
        return Lock(path, pid, create_time)
    return None


def release_lock(lock: Lock) -> None:
    with contextlib.suppress(OSError):
        holder = _holder(lock.path)
        if holder is not None and holder[0] == lock.pid:
            lock.path.unlink(missing_ok=True)


# ── 托盘信息 / IPC ────────────────────────────────────────────────────
def _read_info() -> dict[str, Any] | None:
    data = _read_json(paths.data_dir() / INFO_NAME)
    if data is None:
        return None
    try:
        if int(data["port"]) <= 0 or not str(data["token"]):
            return None
        int(data["pid"])
        float(data["create_time"])
    except (KeyError, TypeError, ValueError):
        return None
    return data


def running() -> tuple[int, int] | None:
    """正在运行的托盘 ``(pid, IPC 端口)``；没有或信息已过期返回 ``None``。"""
    info = _read_info()
    if info is None:
        return None
    try:
        pid = int(info["pid"])
        if not _alive(pid, float(info["create_time"])):
            return None
        return pid, int(info["port"])
    except (KeyError, TypeError, ValueError):
        return None


def _write_info(data: dict[str, Any]) -> None:
    paths.write_atomic(paths.ensure_data_dir() / INFO_NAME, json.dumps(data))


def _clear_info() -> None:
    with contextlib.suppress(OSError):
        (paths.data_dir() / INFO_NAME).unlink(missing_ok=True)


def _request(info: dict[str, Any], command: str, timeout: float) -> str:
    payload = json.dumps({"token": info["token"], "command": command}).encode() + b"\n"
    with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=CONNECT_TIMEOUT) as conn:
        conn.settimeout(timeout)
        conn.sendall(payload)
        line = conn.makefile("rb").readline(65536)
    reply = json.loads(line or b"{}")
    if not isinstance(reply, dict) or not reply.get("ok"):
        error = reply.get("error") if isinstance(reply, dict) else None
        raise RuntimeError(str(error or "托盘拒绝请求"))
    return str(reply.get("result") or "")


def send_open(timeout: float, *, wait: float = 0.0) -> str:
    """让托盘打开窗口；``wait`` 内反复重试等待托盘就绪。"""
    deadline = time.monotonic() + wait
    while True:
        info = _read_info()
        if info is not None and _alive(int(info["pid"]), float(info["create_time"])):
            try:
                return _request(info, "open", timeout)
            except (OSError, ValueError):
                pass  # 托盘正在启动/退出，短暂重试
        if time.monotonic() >= deadline:
            raise TrayUnavailable("没有运行中的托盘")
        time.sleep(0.2)


class IpcServer:
    """只接受 loopback + 随机 token 的「打开窗口」请求。"""

    def __init__(self, handler: Callable[[str], str], token: str) -> None:
        self._handler = handler
        self._token = token
        self._closed = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = int(self._sock.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="dsh-tray-ipc", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._closed.set()
        with contextlib.suppress(OSError):
            self._sock.close()

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), name="dsh-tray-ipc-conn", daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            try:
                conn.settimeout(CONNECT_TIMEOUT)
                request = json.loads(conn.makefile("rb").readline(8192) or b"{}")
            except (OSError, ValueError):
                return
            if not isinstance(request, dict):
                return

            if not hmac.compare_digest(str(request.get("token", "")).encode(), self._token.encode()):
                reply: dict[str, Any] = {"ok": False, "error": "unauthorized"}
            else:
                try:
                    reply = {"ok": True, "result": self._handler(str(request.get("command", "")))}
                except Exception as exc:  # noqa: BLE001 - 把失败原因回传给发起方
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            with contextlib.suppress(OSError):
                conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode())


# ── 托盘本体 ──────────────────────────────────────────────────────────
class TrayApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.controller = service.Service(settings)
        self.icon: Any = None
        self.server: IpcServer | None = None
        self._busy = threading.Lock()
        self._details_lock = threading.Lock()
        self._stopping = threading.Event()
        self._title_stop = threading.Event()

    def run(self) -> int:
        import pystray

        self.icon = pystray.Icon("dshlauncher", icon_image(), TITLE, menu=self._menu(pystray))
        token = secrets.token_hex(16)
        self.server = IpcServer(self._ipc, token)
        self.server.start()
        _write_info(
            {
                "pid": os.getpid(),
                "create_time": psutil.Process().create_time(),
                "port": self.server.port,
                "token": token,
            }
        )
        _print("托盘已启动：左键打开窗口，右键打开菜单。")
        try:
            self.icon.run(setup=self._setup)
        except KeyboardInterrupt:
            paths.audit("tray: Ctrl+C，停止服务后退出")
            with contextlib.suppress(Exception), self._busy:
                self.controller.stop()
        finally:
            self._shutdown()
        return 0

    # ── 菜单 ──────────────────────────────────────────────────────────
    def _menu(self, pystray: Any) -> Any:
        menu_item = pystray.MenuItem
        return pystray.Menu(
            menu_item(
                "打开窗口",
                self._action("打开窗口", lambda: actions.open_dsh(self.settings), quiet=True),
                default=True,
            ),
            menu_item(lambda item: f"服务状态：{state_text(self.controller)}…", self._details),
            pystray.Menu.SEPARATOR,
            menu_item("停止服务", self._action("停止服务", self._stop_service)),
            menu_item("重启服务", self._action("重启服务", lambda: actions.restart(self.settings))),
            menu_item("刷新状态", lambda icon, item: self._refresh()),
            pystray.Menu.SEPARATOR,
            menu_item("查看日志", self._action("查看日志", self._open_log)),
            menu_item("打开数据目录", self._action("打开数据目录", self._open_data_dir)),
            pystray.Menu.SEPARATOR,
            menu_item("退出并停止服务", self._quit),
        )

    def _action(
        self, label: str, work: Callable[[], Any], *, quiet: bool = False
    ) -> Callable[[Any, Any], None]:
        """菜单回调必须立即返回：重活在后台线程里跑，避免卡住托盘消息循环。

        ``quiet`` 用于「打开窗口」：双击托盘图标会触发两次默认动作，第二次
        静默忽略即可，不该弹「操作进行中」。
        """

        def handler(icon: Any, item: Any) -> None:
            if self._stopping.is_set():
                if not quiet:
                    self._notify("托盘正在退出")
                return
            if not self._busy.acquire(blocking=False):
                if not quiet:
                    self._notify(BUSY_TEXT)
                return
            threading.Thread(
                target=self._work, args=(label, work), name=f"dsh-tray-{label}", daemon=True
            ).start()

        return handler

    def _work(self, label: str, work: Callable[[], Any]) -> None:
        try:
            result = work()
            paths.audit(f"tray {label}: {result or 'ok'}")
        except Exception as exc:  # noqa: BLE001 - 托盘统一转成气泡 + 审计
            text = f"{label}失败：{type(exc).__name__}: {exc}"
            paths.audit(text, detail=traceback.format_exc())
            self._notify(text)
        finally:
            self._busy.release()
            self._refresh()

    # ── 动作 ──────────────────────────────────────────────────────────
    def _setup(self, icon: Any) -> None:
        icon.visible = True
        threading.Thread(target=self._title_loop, daemon=True).start()
        with self._busy:
            try:
                result = actions.open_dsh(self.settings)
                paths.audit("tray open: " + result)
            except Exception as exc:  # noqa: BLE001 - 托盘启动失败也要留在任务栏
                text = f"打开窗口失败：{type(exc).__name__}: {exc}"
                paths.audit(text, detail=traceback.format_exc())
                self._notify(text)
        self._refresh()

    def _stop_service(self) -> str:
        return "已停止服务" if self.controller.stop() else "服务未在运行"

    def _open_log(self) -> str:
        paths.ensure_data_dir()
        paths.log_path().touch(exist_ok=True)
        platform.load().open_path(paths.log_path())
        return f"已打开 {paths.log_path()}"

    def _open_data_dir(self) -> str:
        platform.load().open_path(paths.ensure_data_dir())
        return f"已打开 {paths.data_dir()}"

    def _details(self, icon: Any = None, item: Any = None) -> None:
        """菜单只显示短状态；详情放进原生弹窗，避免菜单过宽。"""
        if self._stopping.is_set() or not self._details_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._show_details, name="dsh-tray-details", daemon=True).start()

    def _show_details(self) -> None:
        try:
            text = self.controller.describe()
        except Exception as exc:  # noqa: BLE001 - 弹窗仍然要显示失败原因
            text = f"读取状态失败：{type(exc).__name__}: {exc}"
            paths.audit(text, detail=traceback.format_exc())
        try:
            paths.audit("tray 服务状态: " + (text.splitlines() or [""])[0])
            platform.load().message(f"{TITLE} 服务状态", text)
        except Exception as exc:  # noqa: BLE001 - 弹窗失败也要留痕
            paths.audit(f"tray 服务状态失败: {type(exc).__name__}: {exc}", detail=traceback.format_exc())
            self._notify(f"打开状态窗口失败：{exc}")
        finally:
            self._details_lock.release()

    def _ipc(self, command: str) -> str:
        if command != "open":
            raise ValueError(f"未知命令：{command}")
        if self._stopping.is_set():
            raise RuntimeError("托盘正在退出")
        with self._busy:
            result = actions.open_dsh(self.settings)
        paths.audit("tray ipc open: " + result)
        self._refresh()
        return result

    def _quit(self, icon: Any = None, item: Any = None) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        threading.Thread(target=self._stop_and_quit, name="dsh-tray-quit", daemon=True).start()

    def _stop_and_quit(self) -> None:
        try:
            with self._busy:
                stopped = self.controller.stop()
            paths.audit("tray quit: " + ("服务已停止" if stopped else "服务未在运行"))
        except Exception as exc:  # noqa: BLE001 - 停服务失败也要退出托盘
            paths.audit(f"tray quit: 停止服务失败 {type(exc).__name__}: {exc}", detail=traceback.format_exc())
            self._notify(f"停止服务失败：{exc}")
        with contextlib.suppress(Exception):
            self.icon.stop()

    # ── 刷新 / 通知 / 收尾 ───────────────────────────────────────────
    def _title_loop(self) -> None:
        while not self._title_stop.wait(TITLE_INTERVAL):
            self._refresh_title()

    def _refresh_title(self) -> None:
        with contextlib.suppress(Exception):
            self.icon.title = f"{TITLE} — {status_text(self.controller)}"

    def _refresh(self) -> None:
        self._refresh_title()
        with contextlib.suppress(Exception):
            self.icon.update_menu()

    def _notify(self, text: str) -> None:
        rows = [row for row in str(text).splitlines() if row.strip()]
        message = "\n".join(rows[:4])
        if len(message) > 250:
            message = message[:247] + "…"
        with contextlib.suppress(Exception):
            self.icon.notify(message, TITLE)

    def _shutdown(self) -> None:
        self._stopping.set()
        self._title_stop.set()
        if self.server is not None:
            self.server.close()
        _clear_info()


# ── 入口 ──────────────────────────────────────────────────────────────
def _print(text: str) -> None:
    if sys.stdout is None:
        return
    with contextlib.suppress(OSError):
        print(text)


def _open_directly(settings: Settings) -> int:
    result = actions.open_dsh(settings)
    paths.audit("open: " + result)
    _print(result)
    return 0


def _report_request_error(exc: BaseException) -> int:
    # 托盘已经在气泡里报过错了，这里只落日志（有控制台时顺带打印），不再弹窗。
    text = f"托盘请求失败：{type(exc).__name__}: {exc}"
    paths.audit(text)
    _print(text)
    return 1


def run(settings: Settings) -> int:
    """双击 / ``tray`` 的入口：有托盘就投递，没有就自己成为托盘。"""
    timeout = settings.start_timeout + 30
    try:
        result = send_open(timeout, wait=0.0)
    except TrayUnavailable:
        pass
    except RuntimeError as exc:
        return _report_request_error(exc)
    else:
        _print(result)
        return 0

    lock = acquire_lock()
    if lock is None:
        # 另一个实例正在启动托盘：等它就绪后把 open 投递过去。
        try:
            result = send_open(timeout, wait=START_WAIT)
        except TrayUnavailable:
            return _open_directly(settings)
        except RuntimeError as exc:
            return _report_request_error(exc)
        _print(result)
        return 0

    try:
        return TrayApp(settings).run()
    finally:
        release_lock(lock)
