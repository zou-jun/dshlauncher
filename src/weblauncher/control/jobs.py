"""控制台后台任务：动作/升级等长操作只返回 job id，页面轮询结果。"""

from __future__ import annotations

import collections
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    id: str
    label: str
    status: str = "running"
    result: Any = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: collections.OrderedDict[str, Job] = collections.OrderedDict()

    def submit(self, label: str, work: Any) -> Job:
        job = Job(id=secrets.token_hex(8), label=label)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > 50:
                self._jobs.popitem(last=False)
        thread = threading.Thread(
            target=self._run,
            args=(job, work),
            name=f"control-{job.id}",
            daemon=True,
        )
        thread.start()
        return job

    def _run(self, job: Job, work: Any) -> None:
        try:
            job.result = work()
        except Exception as exc:  # noqa: BLE001 - 任务失败必须回给页面
            job.error = f"{type(exc).__name__}: {exc}"
            job.status = "failed"
        else:
            job.status = "succeeded"
        finally:
            job.finished_at = time.time()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return [job.as_dict() for job in reversed(self._jobs.values())][:20]


__all__ = ["Job", "JobManager"]
