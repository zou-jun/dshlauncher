"""dsh web 服务的启动、停止、状态与就绪判定（平台无关）。"""

from __future__ import annotations

import contextlib
import json
import os
import re
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import psutil

from . import discovery, paths, platform, ports
from .settings import Settings

#: 每次启动写入日志的标记行；只有它之后的 URL 属于当前进程（token 每进程都变）。
START_MARKER = "[launcher] start"
URL_PATTERN = re.compile(r"dsh web: (https?://\S+)")
BIN_JS_MARKER = "@deepseek-ai/dsh/lib/bin.js"
#: 外部手动启动的 dsh 可能是 PATH 上的 shim（符号链接/脚本），不一定带 bin.js 路径。
DSH_NAMES = {"dsh", "dsh.cmd", "dsh.exe", "dsh.js"}

STOP_TIMEOUT = 10.0
LOG_ROTATE_BYTES = 5 * 1024 * 1024
TAIL_BYTES = 256 * 1024


@dataclass
class State:
    pid: int
    create_time: float
    port: int
    url: str | None = None


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
    """取最后一个启动标记之后的 token URL（标记之前的是上一个进程的）。"""
    marker = text.rfind(START_MARKER)
    if marker != -1:
        text = text[marker:]
    matches = URL_PATTERN.findall(text)
    return matches[-1] if matches else None


def url_port(url: str) -> int | None:
    """URL 里的端口；解析失败返回 None。"""
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def startup_failure(text: str, lines: int = 12) -> str:
    """捞出本次启动的失败原因，而不是把日志尾部整块丢给用户。

    dsh 失败时会先打印 ``dsh: startup failed`` 块（真正的 EOF 原因），随后才是
    「插件在等某个服务」的长表；只 tail 最后几行必然只剩后者。
    """
    marker = text.rfind(START_MARKER)
    if marker != -1:
        text = text[marker:]
    rows = text.splitlines()
    for index, row in enumerate(rows):
        if "startup failed" in row:
            block: list[str] = []
            for line in rows[index:]:
                stripped = line.strip()
                # 失败块之后是「插件在等某个服务」的长表和诊断路径，都不是原因。
                if stripped.startswith(("Plugins waiting", "Full diagnostics")):
                    break
                if stripped.startswith("at "):
                    continue
                if not stripped and block and not block[-1].strip():
                    continue
                block.append(line)
                if len(block) >= lines:
                    break
            return "\n".join(block).strip()
    return "\n".join(rows[-lines:]).strip()


class Service:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = platform.load()
        #: 本次实际使用的端口；首次访问时解析（显式端口原样，默认端口自动回退）。
        self._port: int | None = None

    # ── 端口 ──────────────────────────────────────────────────────────
    def effective_port(self) -> int:
        """本次会用的端口，不启动服务（`status` / `doctor` 也用它）。"""
        if self._port is None:
            self._port = self._plan_port()
        return self._port

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
        try:
            data = json.loads(paths.state_path().read_text("utf-8"))
            return State(int(data["pid"]), float(data["create_time"]), int(data["port"]), data.get("url"))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def write_state(self, state: State) -> None:
        paths.ensure_data_dir()
        paths.write_atomic(paths.state_path(), json.dumps(asdict(state), indent=2))

    def _log_text(self) -> str:
        """日志尾部（最多 TAIL_BYTES），覆盖最近一次启动。"""
        try:
            with paths.log_path().open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - TAIL_BYTES))
                return handle.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def latest_url(self) -> str | None:
        return parse_url(self._log_text())

    def _rotate_log(self) -> None:
        log = paths.log_path()
        try:
            if log.exists() and log.stat().st_size > LOG_ROTATE_BYTES:
                rotated = log.with_suffix(".log.1")
                rotated.unlink(missing_ok=True)
                log.replace(rotated)
        except OSError:
            pass

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

    def dsh_processes(self) -> list[psutil.Process]:
        """命令行匹配 dsh web 的进程（清理无 state 的残留）。"""
        found: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
            except psutil.Error:
                continue
            joined = " ".join(str(part) for part in cmdline)
            if is_dsh_cmdline(joined):
                found.append(proc)
        return found

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
        self._port = state.port
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
        self._port = None

        port = self.effective_port()
        verdict = ports.probe(self.settings.host, port)
        if verdict.in_use:
            owner = self.port_owner_process(port)
            if owner is not None and self._is_dsh_process(owner):
                paths.audit(f"takeover: 端口 {port} 上的外部 dsh web pid={owner.pid}")
                self._kill_tree(owner.pid)
                self._wait_port_closed(port)
                verdict = ports.probe(self.settings.host, port)
            if not verdict.free and not self.settings.port_explicit:
                # 旧实例的监听句柄可能被它的子进程继承，端口迟迟不释放：换候选。
                self._port = self._plan_port(frozenset({port}))
                paths.audit(f"port: {port} 仍被占用，改用 {self._port}")
                port = self._port
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
        paths.ensure_data_dir()
        self._rotate_log()
        node = discovery.node_exe(self.settings.node)
        bin_js = discovery.dsh_bin(self.settings.dsh_bin)
        args = [
            str(node),
            str(bin_js),
            "web",
            "--no-open",
            "--host",
            self.settings.host,
            "--port",
            str(port),
        ]
        log = paths.log_path().open("ab", buffering=0)
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
            paths.state_path().unlink(missing_ok=True)
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
                    + f"\n完整日志：{paths.log_path()}"
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
            + f"\n完整日志：{paths.log_path()}"
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
            paths.state_path().unlink(missing_ok=True)
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
        paths.state_path().unlink(missing_ok=True)
        return True

    def ensure(self) -> tuple[State, bool]:
        """保证服务在跑并返回 (state, 是否本次新启动)。"""
        state = self.read_state()
        if state is not None and self.live_process(state) is not None:
            return self._reuse(state), False
        return self.start(), True

    # ── 展示 ──────────────────────────────────────────────────────────
    def describe(self, *, english: bool = False) -> str:
        state = self.read_state()
        proc = self.live_process(state)
        if state is not None and proc is not None:
            self._port = state.port
        port = self.effective_port()
        running = proc is not None
        listening = self.port_open(port)
        url = self.latest_url() if running else None
        pid = proc.pid if proc is not None else "-"
        warning = not running and listening
        # port_owner() 要枚举整张 TCP 表；只在确实要提示占用者时才查。
        owner = (self.port_owner(port) or ("unknown" if english else "未知")) if warning else ""

        if english:
            lines = [
                f"Service : {'running' if running else 'stopped'}",
                f"PID     : {pid}",
                f"Port    : {self.settings.host}:{port} ({'LISTENING' if listening else 'closed'})",
                f"URL     : {url or '-'}",
                f"Workdir : {self.settings.work_dir}",
                f"Data    : {paths.data_dir()}",
                f"Log     : {paths.log_path()}",
            ]
            if warning:
                lines.append(f"Warning : port held by -> {owner}")
            return "\n".join(lines)

        lines = [
            f"服务: {'运行中' if running else '未运行'}",
            f"PID : {pid}",
            f"端口: {self.settings.host}:{port} ({'LISTENING' if listening else 'closed'})",
            f"URL : {url or '-'}",
            f"工作目录: {self.settings.work_dir}",
            f"数据目录: {paths.data_dir()}",
            f"日志: {paths.log_path()}",
        ]
        if warning:
            lines.append(f"注意: 端口被外部进程占用 -> {owner}")
        return "\n".join(lines)
