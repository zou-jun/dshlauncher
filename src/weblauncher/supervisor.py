"""通用服务生命周期：端口规划、分离启动、就绪等待、停止与状态快照。

具体服务的 argv、鉴权、就绪判定与优雅停止全部由
``services.base.ServiceAdapter`` 提供，这里不出现任何服务名。
"""

from __future__ import annotations

import contextlib
import socket
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import psutil

from . import inspector, logs, platform, ports, process
from . import state as state_mod
from .paths import Paths, ServicePaths, open_append
from .services.base import LaunchPlan, ServiceAdapter, ServiceSpec
from .state import State
from .status import ServiceStatus

STOP_TIMEOUT = 10.0


class Supervisor:
    def __init__(
        self,
        adapter: ServiceAdapter,
        *,
        paths_: Paths | None = None,
        backend: object | None = None,
        other_ports: Callable[[], set[int]] | None = None,
    ) -> None:
        self.adapter = adapter
        self.spec: ServiceSpec = adapter.spec
        self.settings = adapter.settings
        self.paths = paths_ or Paths.current()
        self.service_paths: ServicePaths = self.paths.service(self.spec.id)
        self.backend = backend or platform.load()
        self._other_ports = other_ports or (lambda: set())
        self.start_timeout = float(getattr(self.settings, "start_timeout", 120.0))
        self._lock_depth = 0
        self._lock: process.ServiceLock | None = None
        self._inspector = inspector.PortInspector()

    @contextlib.contextmanager
    def _locked(self):
        """序列化同一服务的跨进程 start/stop/restart；实例内可重入。"""
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        lock = process.ServiceLock(
            self.service_paths.lock,
            timeout=self.start_timeout + STOP_TIMEOUT + 5.0,
            label=self.spec.label,
        )
        lock.acquire()
        self._lock = lock
        self._lock_depth = 1
        try:
            yield
        finally:
            self._lock_depth = 0
            self._lock = None
            lock.release()

    # ── 端口 ──────────────────────────────────────────────────────────
    def effective_port(self) -> int:
        """本次会用的端口，不启动服务；不缓存，读操作不改实例状态。"""
        return self._plan_port()

    def _plan_port(self, exclude: frozenset[int] = frozenset()) -> int:
        if getattr(self.settings, "port_explicit", False):
            return int(self.settings.port)
        state = self.read_state()
        blocked = set(self._other_ports()) | set(exclude)
        for port in ports.candidates(
            state.port if state else None,
            int(self.settings.port),
            fallback=self.spec.fallback_ports or ports.FALLBACK_PORTS,
        ):
            if port in blocked:
                continue
            verdict = ports.probe(self.settings.host, port)
            if verdict.free:
                return port
            if verdict.in_use and self.spec.takeover and self._owner_matches(port):
                return port
        return int(self.settings.port)

    def _owner_matches(self, port: int) -> bool:
        owner = self.port_owner_process(port)
        return owner is not None and self._is_owned(owner, port)

    def _port_hint(self) -> str:
        if getattr(self.settings, "port_explicit", False):
            fallback = self.spec.fallback_ports[0] if self.spec.fallback_ports else ports.FALLBACK_PORTS[0]
            return f"显式指定的端口不可用，换一个：--port {fallback}（去掉 --port 则自动选）"
        return "自动选端口失败，请用 --port 指定一个系统未保留的端口"

    # ── 状态文件 / 日志 ────────────────────────────────────────────────
    def port_open(self, port: int | None = None, timeout: float = 0.3) -> bool:
        port = int(self.settings.port) if port is None else port
        host = str(self.settings.host)
        if host in {"0.0.0.0", ""}:
            host = "127.0.0.1"
        elif host == "::":
            host = "::1"
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def read_state(self) -> State | None:
        return state_mod.read_state(self.service_paths.state)

    def write_state(self, state: State) -> None:
        state_mod.write_state(self.service_paths.state, state)

    def _log_text(self) -> str:
        return logs.tail_text(self.service_paths.log)

    def latest_url(self) -> str | None:
        return self.adapter.url_from_log(self._log_text())

    def _rotate_log(self) -> None:
        logs.rotate(self.service_paths.log)

    # ── 进程判定 ──────────────────────────────────────────────────────
    def _cmdline(self, proc: psutil.Process) -> str:
        try:
            return " ".join(proc.cmdline())
        except (psutil.Error, OSError):
            return ""

    def _is_owned(self, proc: psutil.Process, port: int | None = None) -> bool:
        return self.adapter.owns_process(self._cmdline(proc), port)

    def live_process(self, state: State | None) -> psutil.Process | None:
        """state.json 里的服务进程；create_time 不符视为 PID 被复用。"""
        if state is None:
            return None
        try:
            proc = psutil.Process(state.pid)
            if abs(proc.create_time() - state.create_time) > 1.0:
                return None
        except psutil.Error:
            return None
        return proc if self._is_owned(proc, state.port) else None

    def port_owner_process(self, port: int | None = None) -> psutil.Process | None:
        port = int(self.settings.port) if port is None else port
        return self._inspector.owner_process(port)

    def _wait_port_closed(self, port: int, timeout: float = STOP_TIMEOUT) -> None:
        """等到端口真正可 bind：connect 被拒不代表旧 socket 已经释放。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if ports.probe(self.settings.host, port).free:
                return
            time.sleep(0.1)

    def port_owner(self, port: int | None = None) -> str | None:
        port = int(self.settings.port) if port is None else port
        return self._inspector.owner(port)

    # ── 生命周期 ──────────────────────────────────────────────────────
    def _reuse(self, state: State) -> State:
        if not state.url:
            state.url = self.latest_url()
        if not self.port_open(state.port):
            plan = LaunchPlan(
                argv=[],
                env={},
                cwd=self.adapter.work_dir(),
                url=state.url,
                token=state.token,
            )
            state.url = self._wait_ready(state, plan)
        self.write_state(state)
        return state

    def start(self) -> State:
        with self._locked():
            return self._start_locked()

    def _start_locked(self) -> State:
        existing = self.read_state()
        if existing is not None and self.live_process(existing) is not None:
            moving = getattr(self.settings, "port_explicit", False) and int(self.settings.port) not in {
                0,
                existing.port,
            }
            if not moving:
                return self._reuse(existing)
            self.stop()

        port = self.effective_port()
        verdict = ports.probe(self.settings.host, port)
        if verdict.in_use:
            owner = self.port_owner_process(port)
            if owner is not None and self._is_owned(owner, port):
                if not self.spec.takeover:
                    raise RuntimeError(
                        f"端口 {port} 已被 {self.spec.label} 实例占用：{self.port_owner(port) or '未知'}\n"
                        "请先停止该实例，或用 --port 换一个端口。"
                    )
                self.paths.audit(f"takeover: 端口 {port} 上的外部 {self.spec.id} pid={owner.pid}")
                self._kill_tree(owner.pid)
                self._wait_port_closed(port)
                verdict = ports.probe(self.settings.host, port)
            if not verdict.free and not getattr(self.settings, "port_explicit", False):
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
                "请先停止该实例，或用 --port 换一个端口。"
            )

        self.service_paths.ensure()
        self._rotate_log()
        plan = self.adapter.prepare(host=str(self.settings.host), port=port)
        state = self._spawn(plan, port)
        try:
            state.url = self._wait_ready(state, plan)
        except RuntimeError:
            self._kill_tree(state.pid)
            self.service_paths.state.unlink(missing_ok=True)
            raise
        self.write_state(state)
        return state

    def _spawn(self, plan: LaunchPlan, port: int) -> State:
        log = open_append(self.service_paths.log, binary=True)
        try:
            if plan.marker:
                log.write(
                    plan.marker.format(
                        port=port,
                        at=f"{datetime.now():%Y-%m-%d %H:%M:%S}",
                    ).encode()
                )
            try:
                proc = process.spawn(
                    plan.argv,
                    cwd=plan.cwd,
                    env=plan.env,
                    log=log,
                    backend=self.backend,
                )
            except OSError as exc:
                raise RuntimeError(
                    f"无法启动 {self.spec.label}：{exc}\n命令：{' '.join(plan.argv)}\n工作目录：{plan.cwd}"
                ) from exc
        finally:
            log.close()
        state = State(
            proc.pid,
            psutil.Process(proc.pid).create_time(),
            port,
            url=plan.url,
            token=plan.token,
            extra=dict(plan.extra),
        )
        self.write_state(state)
        return state

    def _wait_ready(self, state: State, plan: LaunchPlan) -> str:
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            if not psutil.pid_exists(state.pid):
                reason = self.adapter.start_failure(self._log_text(), state.port)
                raise RuntimeError(
                    f"{self.spec.label} 启动后立即退出：\n"
                    + (reason or "（日志里没有可读的失败信息）")
                    + f"\n完整日志：{self.service_paths.log}"
                )
            url = self.adapter.ready(
                plan,
                state,
                port_open=lambda port: self.port_open(port),
                log_text=self._log_text,
            )
            if url:
                if state.port == 0:
                    state.port = logs.url_port(url) or state.port
                return url
            time.sleep(0.2)
        raise RuntimeError(
            f"{self.spec.label} 在 {int(self.start_timeout)}s 内未就绪：\n"
            + self.adapter.start_failure(self._log_text(), state.port)
            + f"\n完整日志：{self.service_paths.log}"
        )

    def _kill_tree(self, pid: int) -> None:
        process.kill_tree(pid)

    def stop(self, *, force: bool = False) -> bool:
        with self._locked():
            return self._stop_locked(force=force)

    def _stop_locked(self, *, force: bool = False) -> bool:
        state = self.read_state()
        proc = self.live_process(state)
        targets: list[psutil.Process] = []
        port = int(self.settings.port)

        if proc is not None and state is not None:
            port = state.port
            targets = [proc]
        elif self.spec.stop_untracked or force:
            candidates = [int(self.settings.port)]
            if state is not None and state.port not in candidates:
                candidates.append(state.port)
            planned = self.effective_port()
            if planned not in candidates:
                candidates.append(planned)
            for candidate in candidates:
                owner = self.port_owner_process(candidate)
                if owner is not None and self._is_owned(owner, candidate):
                    port = candidate
                    targets = [owner]
                    break

        if not targets:
            self.service_paths.state.unlink(missing_ok=True)
            return False

        graceful = False
        if state is not None and targets == [proc]:
            with contextlib.suppress(Exception):
                graceful = bool(self.adapter.request_stop(state))
        if graceful:
            self._wait_port_closed(port)
            if not self.port_open(port) and self.live_process(state) is None:
                self.service_paths.state.unlink(missing_ok=True)
                return True

        for target in targets:
            self._kill_tree(target.pid)
        self._wait_port_closed(port)
        if self.port_open(port):
            raise RuntimeError(
                f"已终止进程 {', '.join(str(target.pid) for target in targets)}，但 "
                f"{self.settings.host}:{port} 仍被占用：{self.port_owner(port) or '未知'}；"
                "state.json 已保留，稍后重试 stop"
            )
        self.service_paths.state.unlink(missing_ok=True)
        return True

    def ensure(self) -> tuple[State, bool]:
        """保证服务在跑并返回 (state, 是否本次新启动)。"""
        with self._locked():
            state = self.read_state()
            if state is not None and self.live_process(state) is not None:
                return self._reuse(state), False
            return self._start_locked(), True

    def restart(self) -> State:
        """在同一个锁内 stop + start，避免中间被其它进程插队。"""
        with self._locked():
            self._stop_locked()
            return self._start_locked()

    # ── 展示 ──────────────────────────────────────────────────────────
    def status(self, *, check_ports: bool = True, check_owner: bool = False) -> ServiceStatus:
        state = self.read_state()
        proc = self.live_process(state)
        running = proc is not None
        port = state.port if state is not None and running else int(self.settings.port)
        listening = self.port_open(port) if check_ports else False
        url = None
        if running and check_ports:
            url = state.url if state is not None and state.url else self.latest_url()
        owner = self.port_owner(port) if check_owner and not running and listening else None
        extra = self.adapter.status_extra(state) if state is not None else {}
        work_dir = self.adapter.work_dir()
        if running and extra.get("root_dir"):
            work_dir = Path(extra["root_dir"])
        return ServiceStatus(
            running=running,
            pid=proc.pid if proc is not None else None,
            host=str(self.settings.host),
            port=port,
            listening=listening,
            url=url,
            work_dir=work_dir,
            data_dir=self.service_paths.root,
            log_path=self.service_paths.log,
            owner=owner,
            service_id=self.spec.id,
            label=self.spec.label,
            extra=extra,
        )

    def describe(self, *, english: bool = False) -> str:
        return self.status(check_owner=True).full(english=english)
