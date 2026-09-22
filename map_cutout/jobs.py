from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from time import time
from uuid import uuid4

from .errors import chinese_error


@dataclass
class _Job:
    id: str
    state: str = "queued"
    progress: float = 0.0
    message: str = "等待处理"
    result: object = None
    created_at: float = field(default_factory=time)
    future: Future | None = None

    def payload(self):
        return {"id": self.id, "state": self.state, "progress": self.progress,
                "message": self.message, "result": self.result}


class JobManager:
    def __init__(self, max_workers: int = 1):
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="map-cutout")
        self.jobs: dict[str, _Job] = {}
        self.lock = Lock()

    def submit(self, function, *args, **kwargs) -> str:
        job = _Job(uuid4().hex)
        with self.lock:
            self.jobs[job.id] = job

        def run():
            job.state, job.message = "running", "正在处理"
            try:
                job.result = function(*args, **kwargs)
                job.state, job.progress, job.message = "completed", 1.0, "处理完成"
            except BaseException as exc:
                job.state, job.message = "failed", chinese_error(exc)
            return job.result

        job.future = self.executor.submit(run)
        return job.id

    def status(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job.payload()

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        cancelled = bool(job.future and job.future.cancel())
        if cancelled:
            job.state, job.message = "cancelled", "已取消"
        return cancelled

