"""后台 Job：成功、失败、唯一 ID 与保留上限。"""

from __future__ import annotations

import time

from weblauncher.control.jobs import JobManager


def _wait(manager: JobManager, job_id: str, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job is not None and job.status != "running":
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} 未在 {timeout}s 内结束")


def test_job_success_exposes_result_and_timestamps() -> None:
    manager = JobManager()
    job = manager.submit("demo", lambda: {"value": 1})
    done = _wait(manager, job.id)
    assert done.status == "succeeded"
    assert done.result == {"value": 1}
    assert done.error is None
    assert done.finished_at is not None
    assert done.finished_at >= done.started_at


def test_job_failure_exposes_exception_without_raising_in_submit() -> None:
    manager = JobManager()

    def fail():
        raise ValueError("boom")

    job = manager.submit("failure", fail)
    done = _wait(manager, job.id)
    assert done.status == "failed"
    assert done.result is None
    assert "ValueError" in (done.error or "")
    assert "boom" in (done.error or "")


def test_job_ids_are_unique_and_recent_is_newest_first() -> None:
    manager = JobManager()
    jobs = [manager.submit(f"job-{index}", lambda index=index: index) for index in range(3)]
    for job in jobs:
        _wait(manager, job.id)
    assert len({job.id for job in jobs}) == 3
    recent = manager.recent()
    assert [job["label"] for job in recent] == ["job-2", "job-1", "job-0"]


def test_job_history_keeps_only_latest_fifty() -> None:
    manager = JobManager()
    jobs = [manager.submit(f"job-{index}", lambda: None) for index in range(55)]
    _wait(manager, jobs[-1].id)
    assert manager.get(jobs[-1].id) is not None
    assert manager.get(jobs[0].id) is None
    assert len(manager.recent()) == 20
