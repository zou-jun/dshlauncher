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

import psutil

from . import discovery, paths, platform
from .settings import Settings

#: 每次启动写入日志的标记行；只有它之后的 URL 属于当前进程（token 每进程都变）。
START_MARKER = "[launcher] start"
URL_PATTERN = re.compile(r"dsh web: (https?://\S+)")
BIN_JS_MARKER = "@deepseek-ai/dsh/lib/bin.js"

STOP_TIMEOUT = 10.0
LOG_ROTATE_BYTES = 5 * 1024 * 1024
TAIL_BYTES = 256 * 1024


@dataclass
class State:
    pid: int
    create_time: float
    port: int
    url: str | None = None


def parse_url(text: str) -> str | None:
    """取最后一个启动标记之后的 token URL（标记之前的是上一个进程的）。"""
    marker = text.rfind(START_MARKER)
    if marker != -1:
        text = text[marker:]
    matches = URL_PATTERN.findall(text)
    return matches[-1] if matches else None


class Service:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = platform.load()

    # ── 状态文件 / 日志 ────────────────────────────────────────────────
    def port_open(self, timeout: float = 0.3) -> bool:
        try:
            with socket.create_connection((self.settings.host, self.settings.port), timeout=timeout):
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
        paths.state_path().write_text(json.dumps(asdict(state), indent=2), "utf-8")

    def latest_url(self) -> str | None:
        try:
            with paths.log_path().open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - TAIL_BYTES))
                return parse_url(handle.read().decode("utf-8", "replace"))
        except OSError:
            return None

    def tail_log(self, lines: int = 15) -> str:
        try:
            text = paths.log_path().read_text("utf-8", errors="replace")
        except OSError:
            return "（无日志）"
        return "\n".join(text.splitlines()[-lines:])

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
        return BIN_JS_MARKER in cmdline.replace("\\", "/")

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
        """命令行里带 dsh bin.js + web 的 node 进程（清理无 state 的残留）。"""
        found: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
            except psutil.Error:
                continue
            joined = " ".join(str(part) for part in cmdline).replace("\\", "/")
            if BIN_JS_MARKER in joined and " web" in joined:
                found.append(proc)
        return found

    def port_owner(self) -> str | None:
        try:
            connections = psutil.net_connections(kind="tcp")
        except (psutil.Error, OSError):
            return None
        for conn in connections:
            if conn.laddr and conn.laddr.port == self.settings.port and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                if pid is None:
                    return f"未知进程（监听 {self.settings.port}）"
                try:
                    proc = psutil.Process(pid)
                    return f"pid {pid} {proc.name()} :: {' '.join(proc.cmdline())[:200]}"
                except psutil.Error:
                    return f"pid {pid}"
        return None

    # ── 生命周期 ──────────────────────────────────────────────────────
    def start(self) -> State:
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
            str(self.settings.port),
        ]
        log = paths.log_path().open("ab", buffering=0)
        try:
            # 先落标记行，保证之后的 token URL 一定属于本次进程。
            log.write(
                f"\n{START_MARKER} port={self.settings.port} at={datetime.now():%Y-%m-%d %H:%M:%S}\n".encode()
            )
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

        state = State(proc.pid, psutil.Process(proc.pid).create_time(), self.settings.port)
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
                raise RuntimeError("dsh web 启动后立即退出，日志末尾：\n" + self.tail_log())
            url = self.latest_url()
            if url and self.port_open():
                return url
            time.sleep(0.2)
        raise RuntimeError(
            f"dsh web 在 {int(self.settings.start_timeout)}s 内未就绪，日志末尾：\n" + self.tail_log()
        )

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
        targets: list[psutil.Process] = []

        proc = self.live_process(state)
        if proc is not None:
            targets.append(proc)
        elif self.port_open():
            # 没有可信 state，但端口确实被 dsh web 占着：清理该实例。
            targets = self.dsh_processes()

        if not targets:
            paths.state_path().unlink(missing_ok=True)
            return False

        for target in targets:
            self._kill_tree(target.pid)
        paths.state_path().unlink(missing_ok=True)

        deadline = time.monotonic() + STOP_TIMEOUT
        while time.monotonic() < deadline and self.port_open():
            time.sleep(0.1)
        return True

    def ensure(self) -> tuple[State, bool]:
        """保证服务在跑并返回 (state, 是否本次新启动)。"""
        state = self.read_state()
        proc = self.live_process(state)
        if state is not None and proc is not None:
            if not state.url:
                state.url = self.latest_url()
            if not self.port_open():
                state.url = self._wait_ready(state)
            self.write_state(state)
            return state, False

        if self.port_open():
            raise RuntimeError(
                f"端口 {self.settings.port} 已被其它进程占用：{self.port_owner() or '未知'}\n"
                "请先停止该实例，或用 --port / DSHLAUNCHER_PORT 换一个端口。"
            )

        return self.start(), True

    # ── 展示 ──────────────────────────────────────────────────────────
    def describe(self) -> str:
        state = self.read_state()
        proc = self.live_process(state)
        running = proc is not None
        listening = self.port_open()
        url = self.latest_url() if running else None

        lines = [
            f"服务: {'运行中' if running else '未运行'}",
            f"PID : {proc.pid if proc is not None else '-'}",
            f"端口: {self.settings.host}:{self.settings.port} ({'LISTENING' if listening else 'closed'})",
            f"URL : {url or '-'}",
            f"工作目录: {self.settings.work_dir}",
            f"数据目录: {paths.data_dir()}",
            f"日志: {paths.log_path()}",
        ]
        if not running and listening:
            lines.append(f"注意: 端口被外部进程占用 -> {self.port_owner() or '未知'}")
        return "\n".join(lines)
