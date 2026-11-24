"""执行 dsh / profile 插件升级，并记录可轮询的任务状态。"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from ...paths import child_env, open_append
from . import discovery, updates

WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if WINDOWS else 0
LOG_LIMIT = 600
#: 完整升级日志落盘上限，超出后轮转一份 .1。
LOG_ROTATE_BYTES = 1024 * 1024
#: 全局安装 / 插件安装可能比服务启动慢得多，单独设上限。
INSTALL_TIMEOUT = 600.0


class UpgradeError(RuntimeError):
    """升级前置条件或命令执行失败。"""


class BusyError(UpgradeError):
    """已有升级任务或服务动作正在运行。"""


@dataclass
class Step:
    target: str
    label: str
    version: str
    status: str = "pending"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "label": self.label,
            "version": self.version,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class UpgradeJob:
    id: str
    status: str = "running"
    started_at: str = ""
    finished_at: str | None = None
    steps: list[Step] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [step.as_dict() for step in self.steps],
            "log": list(self.log),
            "error": self.error,
        }


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
            target.kill()


class UpgradeManager:
    """单任务升级执行器；HTTP 面板与测试共用。"""

    def __init__(
        self,
        context,
        *,
        exclusive: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.context = context
        self.settings = context.settings
        self.paths = context.paths
        self._exclusive = exclusive
        self._start_lock = threading.Lock()
        self._job_lock = threading.Lock()
        self._file_lock = threading.Lock()
        self._job: UpgradeJob | None = None

    @property
    def job(self) -> UpgradeJob | None:
        with self._job_lock:
            return self._job

    def start(self, targets: list[str], report: updates.UpdateReport) -> dict[str, Any]:
        """校验 target 并启动后台线程；调用方随后轮询 job。"""
        if not isinstance(targets, list) or not targets:
            raise UpgradeError("没有选择要升级的项目")
        if not all(isinstance(target, str) for target in targets):
            raise UpgradeError("targets 必须是字符串数组")

        with self._start_lock:
            current = self.job
            if current is not None and current.status == "running":
                raise BusyError("已有升级任务在运行")

            plan = self._plan(targets, report)
            job = UpgradeJob(
                id=secrets.token_hex(8),
                started_at=_now(),
                steps=[Step(target, label, version) for target, label, version in plan],
            )
            with self._job_lock:
                self._job = job
            self._append_file(f"===== {_now()} job {job.id} targets={','.join(targets)}\n")
            thread = threading.Thread(
                target=self._run,
                args=(job, plan, report),
                name="dsh-upgrade",
                daemon=False,
            )
            thread.start()
            return job.as_dict()

    def _plan(self, targets: list[str], report: updates.UpdateReport) -> list[tuple[str, str, str]]:
        plan: list[tuple[str, str, str]] = []
        if "dsh" in targets:
            dsh = report.dsh
            if not dsh.update_available:
                raise UpgradeError("dsh 已是最新")
            if not dsh.upgrade_supported:
                raise UpgradeError(dsh.detail or "当前安装方式不支持自动升级 dsh")
            plan.append(("dsh", f"{dsh.name} {dsh.current} → {dsh.latest}", dsh.latest))

        by_name = {plugin.name: plugin for plugin in report.profile.plugins}
        for target in targets:
            if target == "dsh":
                continue
            if not target.startswith("plugin:"):
                raise UpgradeError(f"未知升级目标：{target}")
            name = target.removeprefix("plugin:")
            plugin = by_name.get(name)
            if plugin is None:
                raise UpgradeError(f"profile 里没有插件：{name}")
            if not plugin.update_available:
                raise UpgradeError(f"{name} 已是最新")
            plan.append((target, f"{name} {plugin.current} → {plugin.latest}", plugin.latest))

        # dsh 必须先升级：新版插件可能要求新版 dsh。
        plan.sort(key=lambda row: 0 if row[0] == "dsh" else 1)
        return plan

    # ── 后台执行 ──────────────────────────────────────────────────────
    def _run(
        self,
        job: UpgradeJob,
        plan: list[tuple[str, str, str]],
        report: updates.UpdateReport,
    ) -> None:
        try:
            if self._exclusive is None:
                self._execute(job, plan, report)
            else:
                self._exclusive(lambda: self._execute(job, plan, report))
        except Exception as exc:  # noqa: BLE001 - 任务状态必须承载所有失败
            self._finish(job, "failed", f"{type(exc).__name__}: {exc}")

    def _execute(
        self,
        job: UpgradeJob,
        plan: list[tuple[str, str, str]],
        report: updates.UpdateReport,
    ) -> None:
        service = self.context.service()
        try:
            was_running = service.status(check_ports=False).running
        except Exception as exc:  # noqa: BLE001 - 读不到状态按未运行处理
            was_running = False
            self._log(job, f"读取服务状态失败：{type(exc).__name__}: {exc}")

        self._log(job, f"服务{'运行中' if was_running else '未运行'}")
        stopped = False
        dsh_failed = False
        restart_error: str | None = None
        try:
            if was_running:
                self._log(job, "停止 dsh 服务…")
                try:
                    stopped = service.stop()
                except Exception as exc:  # noqa: BLE001 - 停不下来就不能动全局包
                    self._finish(job, "failed", f"停止服务失败：{type(exc).__name__}: {exc}")
                    return
                if stopped:
                    self._log(job, "服务已停止")
                else:
                    self._log(job, "服务状态显示运行中，但停止时未找到实例")

            for step, (target, label, version) in zip(job.steps, plan, strict=True):
                if dsh_failed and target != "dsh":
                    step.status = "skipped"
                    step.detail = "dsh 升级失败，已跳过"
                    continue
                step.status = "running"
                self._log(job, f"开始升级 {label}")
                try:
                    if target == "dsh":
                        detail = self._upgrade_dsh(job, version, report)
                    else:
                        detail = self._upgrade_plugin(job, target.removeprefix("plugin:"), version, report)
                    step.status = "ok"
                    step.detail = detail
                    self._log(job, f"完成 {label}：{detail}")
                except Exception as exc:  # noqa: BLE001 - 单个插件失败不阻断后续插件
                    step.status = "failed"
                    step.detail = f"{type(exc).__name__}: {exc}"
                    self._log(job, f"失败 {label}：{step.detail}")
                    if target == "dsh":
                        dsh_failed = True
        finally:
            # 无论升级命令本身是否抛异常，只要服务是本次停掉的，都必须尝试拉起。
            if was_running and stopped:
                self._log(job, "启动 dsh 服务…")
                try:
                    service.start()
                    self._log(job, "服务已启动")
                except Exception as exc:  # noqa: BLE001 - 包已升级，启动失败仍要上报
                    restart_error = f"服务启动失败：{type(exc).__name__}: {exc}"
                    self._log(job, restart_error)
            elif not was_running:
                self._log(job, "服务未运行，升级后不自动启动")

        failed = [step for step in job.steps if step.status == "failed"]
        skipped = [step for step in job.steps if step.status == "skipped"]
        if restart_error is not None:
            self._finish(job, "failed" if not failed else "partial", restart_error)
        elif dsh_failed:
            self._finish(job, "failed", "dsh 升级失败")
        elif failed:
            self._finish(job, "partial", f"{len(failed)} 个插件升级失败")
        elif skipped:
            self._finish(job, "partial", f"{len(skipped)} 项已跳过")
        else:
            self._finish(job, "succeeded", None)

    def _upgrade_dsh(self, job: UpgradeJob, version: str, report: updates.UpdateReport) -> str:
        manager = report.dsh.manager
        if manager not in {"npm", "pnpm"}:
            raise UpgradeError(report.dsh.detail or "无法识别 dsh 的全局包管理器")
        exe = shutil.which(manager)
        if exe is None:
            raise UpgradeError(f"找不到 {manager}")
        name = report.dsh.name
        if manager == "npm":
            command = [exe, "install", "-g", f"{name}@{version}"]
        else:
            command = [exe, "add", "-g", f"{name}@{version}"]
        self._log(job, "$ " + " ".join(command))
        self._run_streaming(job, command, cwd=None)
        discovery.reset_cache()
        installed = updates.installed_dsh_version(self.settings)
        comparison = updates.compare_versions(installed, version)
        if comparison is None or comparison < 0:
            raise UpgradeError(f"安装完成但当前版本仍是 {installed or '未知'}")
        return f"已升级到 {installed}"

    def _upgrade_plugin(
        self,
        job: UpgradeJob,
        name: str,
        version: str,
        report: updates.UpdateReport,
    ) -> str:
        directory = Path(report.profile.directory)
        node = discovery.node_exe(self.settings.node)
        bin_js = discovery.dsh_bin(self.settings.dsh_bin)
        command = [
            str(node),
            str(bin_js),
            "plugin",
            "--profile",
            report.profile.name,
            "add",
            f"{name}@{version}",
            "--save-exact",
        ]
        self._log(job, "$ " + " ".join(command))
        self._run_streaming(job, command, cwd=directory)
        installed = updates.installed_plugin_version(directory, name)
        comparison = updates.compare_versions(installed, version)
        if comparison is None or comparison < 0:
            raise UpgradeError(f"安装完成但当前版本仍是 {installed or '未知'}")
        return f"已升级到 {installed}"

    def _run_streaming(self, job: UpgradeJob, command: list[str], *, cwd: Path | None) -> None:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(cwd) if cwd is not None else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=child_env(),
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise UpgradeError(f"无法启动 {Path(command[0]).name}：{exc}") from exc

        state = {"timeout": False}

        def expire() -> None:
            state["timeout"] = True
            _kill_tree(process.pid)

        timer = threading.Timer(INSTALL_TIMEOUT, expire)
        timer.daemon = True
        timer.start()
        assert process.stdout is not None
        try:
            with process.stdout:
                for line in process.stdout:
                    cleaned = line.rstrip()
                    if cleaned:
                        self._log(job, cleaned)
            code = process.wait()
        finally:
            timer.cancel()
        if state["timeout"]:
            raise UpgradeError(f"命令超时（{INSTALL_TIMEOUT:.0f}s）")
        if code != 0:
            raise UpgradeError(f"命令退出码 {code}")

    # ── 状态 ──────────────────────────────────────────────────────────
    def _log(self, job: UpgradeJob, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {text[:4000]}"
        with self._job_lock:
            if len(job.log) >= LOG_LIMIT:
                del job.log[0]
            job.log.append(line)
        self._append_file(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text[:4000]}\n")

    def _append_file(self, text: str) -> None:
        """完整日志落盘；失败不影响升级本身。"""
        try:
            self.paths.ensure()
            path = self.paths.upgrades_log
            with self._file_lock:
                if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
                    rotated = path.with_name(path.name + ".1")
                    rotated.unlink(missing_ok=True)
                    path.replace(rotated)
                with open_append(path) as handle:
                    handle.write(text)
        except OSError:
            pass

    def _finish(self, job: UpgradeJob, status: str, error: str | None) -> None:
        with self._job_lock:
            job.status = status
            job.error = error
            job.finished_at = _now()
        if error:
            self._log(job, f"任务结束：{status}，{error}")
        else:
            self._log(job, f"任务结束：{status}")
