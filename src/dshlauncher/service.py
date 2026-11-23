"""dsh web 服务的启动、停止、状态与就绪判定（平台无关）。"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType

import psutil

from . import discovery, logs, paths, platform, ports
from . import state as state_mod
from .logs import START_MARKER
from .paths import Paths
from .settings import Settings
from .state import State
from .status import ServiceStatus

#: 启动器托管的 dsh web 使用的 profile；更新检查与插件升级也针对它。
WEB_PROFILE = "web"

BIN_JS_MARKER = "@deepseek-ai/dsh/lib/bin.js"
#: 外部手动启动的 dsh 可能是 PATH 上的 shim（符号链接/脚本），不一定带 bin.js 路径。
DSH_NAMES = {"dsh", "dsh.cmd", "dsh.exe", "dsh.js"}

STOP_TIMEOUT = 10.0


def is_dsh_cmdline(cmdline: str) -> bool:
    """判断命令行是不是 `dsh web`（兼容 bin.js 路径和 PATH 上的 shim）。

    只认 "dsh 可执行文件 + 紧邻的 web 子命令"，避免把 ``node dsh web.js``
    这类无关进程（Windows 上 `stop` 会清理它们）当成服务。
    """
    joined = cmdline.replace("\\", "/")
    if " web" not in joined:
        return False
    if BIN_JS_MARKER in joined:
        return True
    parts = [part.strip('"') for part in joined.split()]
    return any(
        Path(part).name in DSH_NAMES and parts[index + 1] == "web" for index, part in enumerate(parts[:-1])
    )


def parse_url(text: str) -> str | None:
    return logs.parse_url(text)


def url_port(url: str) -> int | None:
    return logs.url_port(url)


def startup_failure(text: str, lines: int = 12) -> str:
    return logs.startup_failure(text, lines)


class Service:
    def __init__(
        self,
        settings: Settings,
        *,
        paths_: Paths | None = None,
        backend: ModuleType | None = None,
    ) -> None:
        self.settings = settings
        self.paths = paths_ or Paths.current()
        self.backend = backend or platform.load()

    # ── 端口 ──────────────────────────────────────────────────────────
    def effective_port(self) -> int:
        """本次会用的端口，不启动服务；不缓存，读操作不改实例状态。"""
        return self._plan_port()

    def _plan_port(self, exclude: frozenset[int] = frozenset()) -> int:
        if self.settings.port_explicit:
            # 用户点了名就不偷偷换；不可用由 start() 报精确原因。
            return self.settings.port
        state = self.read_state()
        for port in ports.candidates(state.port if state else None, self.settings.port):
            if port in exclude:
                continue
            verdict = ports.probe(self.settings.host, port)
            if verdict.free:
                return port
            if verdict.in_use and self._dsh_owner(port) is not None:
                # 端口上是手动起的 dsh web：沿用旧行为，接管后重启。
                return port
        # 候选全废：仍返回配置端口，让调用方拿到"保留段/被占用"的具体错误。
        return self.settings.port

    def _dsh_owner(self, port: int) -> psutil.Process | None:
        owner = self.port_owner_process(port)
        return owner if owner is not None and self._is_dsh_process(owner) else None

    def _port_hint(self) -> str:
        if self.settings.port_explicit:
            return f"显式指定的端口不可用，换一个：--port {ports.FALLBACK_PORTS[0]}（去掉 --port 则自动选）"
        return "自动选端口失败，请用 --port 指定一个系统未保留的端口"

    # ── 状态文件 / 日志 ────────────────────────────────────────────────
    def port_open(self, port: int | None = None, timeout: float = 0.3) -> bool:
        port = self.settings.port if port is None else port
        try:
            with socket.create_connection((self.settings.host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def read_state(self) -> State | None:
        return state_mod.read_state(self.paths.state)

    def write_state(self, state: State) -> None:
        state_mod.write_state(self.paths.state, state)

    def _log_text(self) -> str:
        return logs.tail_text(self.paths.log)

    def latest_url(self) -> str | None:
        return logs.parse_url(self._log_text())

    def _rotate_log(self) -> None:
        logs.rotate(self.paths.log)

    # ── 进程判定 ──────────────────────────────────────────────────────
    @staticmethod
    def _is_dsh_process(proc: psutil.Process) -> bool:
        try:
            cmdline = " ".join(proc.cmdline())
        except (psutil.Error, OSError):
            return False
        return is_dsh_cmdline(cmdline)

    def live_process(self, state: State | None) -> psutil.Process | None:
        """pid 文件里的服务进程；create_time 不符视为 PID 被复用。"""
        if state is None:
            return None
        try:
            proc = psutil.Process(state.pid)
            if abs(proc.create_time() - state.create_time) > 1.0:
                return None
        except psutil.Error:
            return None
        return proc if self._is_dsh_process(proc) else None

    def port_owner_process(self, port: int | None = None) -> psutil.Process | None:
        """监听该端口的进程（无法获取时返回 None）。"""
        port = self.settings.port if port is None else port
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.Error, OSError):
            return None
        for conn in connections:
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN and conn.pid:
                try:
                    return psutil.Process(conn.pid)
                except psutil.Error:
                    return None
        return None

    def _wait_port_closed(self, port: int, timeout: float = STOP_TIMEOUT) -> None:
        """等到端口真正可 bind：connect 被拒不代表旧 socket 已经释放。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ports.probe(self.settings.host, port).free:
                return
            time.sleep(0.1)

    def port_owner(self, port: int | None = None) -> str | None:
        port = self.settings.port if port is None else port
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.Error, OSError):
            return None
        for conn in connections:
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                if pid is None:
                    return f"未知进程（监听 {port}）"
                try:
                    proc = psutil.Process(pid)
                    return f"pid {pid} {proc.name()} :: {' '.join(proc.cmdline())[:200]}"
                except psutil.Error:
                    return f"pid {pid}"
        return None

    # ── 生命周期 ──────────────────────────────────────────────────────
    def _reuse(self, state: State) -> State:
        """复用已在运行的实例：刷新 token URL，必要时等它重新就绪。"""
        if not state.url:
            state.url = self.latest_url()
        if not self.port_open(state.port):
            state.url = self._wait_ready(state)
        self.write_state(state)
        return state

    def start(self) -> State:
        existing = self.read_state()
        if existing is not None and self.live_process(existing) is not None:
            moving = self.settings.port_explicit and self.settings.port not in {0, existing.port}
            if not moving:
                # 已经在跑：start / open 都算成功，不重复起第二个实例。
                return self._reuse(existing)
            # 显式要求换个端口：先停掉旧实例，别把它留成孤儿。
            self.stop()

        port = self.effective_port()
        verdict = ports.probe(self.settings.host, port)
        if verdict.in_use:
            owner = self.port_owner_process(port)
            if owner is not None and self._is_dsh_process(owner):
                self.paths.audit(f"takeover: 端口 {port} 上的外部 dsh web pid={owner.pid}")
                self._kill_tree(owner.pid)
                self._wait_port_closed(port)
                verdict = ports.probe(self.settings.host, port)
            if not verdict.free and not self.settings.port_explicit:
                # 旧实例的监听句柄可能被它的子进程继承，端口迟迟不释放：换候选。
                previous = port
                port = self._plan_port(frozenset({port}))
                self.paths.audit(f"port: {previous} 仍被占用，改用 {port}")
                verdict = ports.probe(self.settings.host, port)
        if verdict.reserved:
            raise RuntimeError(
                ports.reserved_message(self.settings.host, port, verdict) + "\n" + self._port_hint()
            )
        if not verdict.free:
            raise RuntimeError(
                f"端口 {port} 已被其它进程占用：{self.port_owner(port) or '未知'}\n"
                "请先停止该实例，或用 --port / DSHLAUNCHER_PORT 换一个端口。"
            )
        self.paths.ensure()
        self._rotate_log()
        node = discovery.node_exe(self.settings.node)
        bin_js = discovery.dsh_bin(self.settings.dsh_bin)
        args = [
            str(node),
            str(bin_js),
            WEB_PROFILE,
            "--no-open",
            "--host",
            self.settings.host,
            "--port",
            str(port),
        ]
        log = self.paths.log.open("ab", buffering=0)
        try:
            # 先落标记行，保证之后的 token URL 一定属于本次进程。
            log.write(f"\n{START_MARKER} port={port} at={datetime.now():%Y-%m-%d %H:%M:%S}\n".encode())
            try:
                proc = subprocess.Popen(
                    args,
                    cwd=str(self.settings.work_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    env=paths.child_env(),
                    **self.backend.detach_kwargs(breakaway=True),
                )
            except OSError:
                # 当前 job 不允许 breakaway 时退回普通分离。
                proc = subprocess.Popen(
                    args,
                    cwd=str(self.settings.work_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    env=paths.child_env(),
                    **self.backend.detach_kwargs(breakaway=False),
                )
        finally:
            log.close()

        state = State(proc.pid, psutil.Process(proc.pid).create_time(), port)
        self.write_state(state)
        try:
            state.url = self._wait_ready(state)
        except RuntimeError:
            self._kill_tree(state.pid)
            self.paths.state.unlink(missing_ok=True)
            raise
        self.write_state(state)
        return state

    def _wait_ready(self, state: State) -> str:
        deadline = time.monotonic() + self.settings.start_timeout
        while time.monotonic() < deadline:
            if not psutil.pid_exists(state.pid):
                reason = startup_failure(self._log_text())
                hint = self._failure_hint(state.port, reason)
                raise RuntimeError(
                    "dsh web 启动后立即退出：\n"
                    + (reason or "（日志里没有可读的失败信息）")
                    + (f"\n{hint}" if hint else "")
                    + f"\n完整日志：{self.paths.log}"
                )
            url = self.latest_url()
            if url and (state.port == 0 or self.port_open(state.port)):
                if state.port == 0:
                    # --port 0：真实端口只在 URL 里，后续 status/stop 都要用它。
                    state.port = url_port(url) or state.port
                return url
            time.sleep(0.2)
        raise RuntimeError(
            f"dsh web 在 {int(self.settings.start_timeout)}s 内未就绪：\n"
            + startup_failure(self._log_text())
            + f"\n完整日志：{self.paths.log}"
        )

    def _failure_hint(self, port: int, reason: str) -> str:
        """把常见的 bind 失败翻译成下一步动作。"""
        if "EACCES" in reason:
            return ports.reserved_message(self.settings.host, port) + "\n" + self._port_hint()
        if "EADDRINUSE" in reason:
            return f"端口 {port} 已被其它进程占用：{self.port_owner(port) or '未知'}"
        return ""

    @staticmethod
    def _kill_tree(pid: int) -> None:
        try:
            proc = psutil.Process(pid)
        except psutil.Error:
            return
        targets: list[psutil.Process] = []
        with contextlib.suppress(psutil.Error):
            targets = proc.children(recursive=True)
        targets.append(proc)
        for target in targets:
            with contextlib.suppress(psutil.Error):
                target.terminate()
        _, alive = psutil.wait_procs(targets, timeout=5)
        for target in alive:
            with contextlib.suppress(psutil.Error):
                target.kill()
        if alive:
            psutil.wait_procs(alive, timeout=3)

    def stop(self) -> bool:
        state = self.read_state()
        proc = self.live_process(state)
        targets: list[psutil.Process] = []
        port = self.settings.port

        if proc is not None and state is not None:
            # state 可信：只停它记录的那个实例和端口。
            port = state.port
            targets = [proc]
        else:
            # state 不可信：只检查配置端口和上次记录的端口，并且只杀 dsh owner。
            candidates = [self.settings.port]
            if state is not None and state.port not in candidates:
                candidates.append(state.port)
            planned = self.effective_port()
            if planned not in candidates:
                candidates.append(planned)
            for candidate in candidates:
                owner = self.port_owner_process(candidate)
                if owner is not None and self._is_dsh_process(owner):
                    port = candidate
                    targets = [owner]
                    break

        if not targets:
            self.paths.state.unlink(missing_ok=True)
            return False

        for target in targets:
            self._kill_tree(target.pid)
        self._wait_port_closed(port)
        if self.port_open(port):
            raise RuntimeError(
                f"已终止进程 {', '.join(str(target.pid) for target in targets)}，但 "
                f"{self.settings.host}:{port} 仍被占用：{self.port_owner(port) or '未知'}；"
                "state.json 已保留，稍后重试 stop"
            )
        self.paths.state.unlink(missing_ok=True)
        return True

    def ensure(self) -> tuple[State, bool]:
        """保证服务在跑并返回 (state, 是否本次新启动)。"""
        state = self.read_state()
        if state is not None and self.live_process(state) is not None:
            return self._reuse(state), False
        return self.start(), True

    # ── 展示 ──────────────────────────────────────────────────────────
    def status(self, *, check_ports: bool = True, check_owner: bool = False) -> ServiceStatus:
        """一次读取的状态快照；读操作不修改实例状态。"""
        state = self.read_state()
        proc = self.live_process(state)
        running = proc is not None
        port = state.port if state is not None and running else self.settings.port
        listening = self.port_open(port) if check_ports else False
        url = None
        if running and check_ports:
            url = state.url if state is not None and state.url else self.latest_url()
        owner = self.port_owner(port) if check_owner and not running and listening else None
        return ServiceStatus(
            running=running,
            pid=proc.pid if proc is not None else None,
            host=self.settings.host,
            port=port,
            listening=listening,
            url=url,
            work_dir=self.settings.work_dir,
            data_dir=self.paths.data,
            log_path=self.paths.log,
            owner=owner,
        )

    def describe(self, *, english: bool = False) -> str:
        return self.status(check_owner=True).full(english=english)
