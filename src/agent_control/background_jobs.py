from __future__ import annotations

import queue
import threading
from typing import Callable, Dict, Optional

from agent_control.models import JobStatus, OperationJob
from agent_control.store import SqliteStore

JobHandler = Callable[[OperationJob], None]


class BackgroundJobRunner:
    """Lightweight in-process worker for long-running run orchestration."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store
        self._handlers: Dict[str, JobHandler] = {}
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="chaos-job-runner", daemon=True)
        self._thread.start()

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def submit(self, job: OperationJob) -> None:
        self.store.save_job(job)
        self._queue.put(job.id)

    def close(self) -> None:
        self._stop_event.set()
        self._queue.put("")
        self._thread.join(timeout=1.0)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            job_id = self._queue.get()
            if not job_id:
                continue
            try:
                job = self.store.get_job(job_id)
            except KeyError:
                continue
            handler = self._handlers.get(job.kind)
            if handler is None:
                self.store.update_job_status(job.id, JobStatus.FAILED, error=f"No handler registered for {job.kind}.")
                continue
            self.store.update_job_status(job.id, JobStatus.RUNNING)
            try:
                handler(self.store.get_job(job.id))
            except Exception as exc:
                self.store.update_job_status(job.id, JobStatus.FAILED, error=str(exc))
            else:
                self.store.update_job_status(job.id, JobStatus.COMPLETED)
