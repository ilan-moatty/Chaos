from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_control.models import (
    Artifact,
    Budget,
    Event,
    JobStatus,
    OperationJob,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    ToolRequest,
    ToolRequestStatus,
    utc_now,
)


class SqliteStore:
    """Durable storage for runs, tasks, artifacts, events, and tool requests."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _init_schema(self) -> None:
        self._executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                required_capability TEXT NOT NULL,
                parent_task_id TEXT,
                owner_agent_id TEXT,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                dependencies_json TEXT NOT NULL,
                artifacts_json TEXT NOT NULL,
                budget_json TEXT NOT NULL,
                inputs_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                task_id TEXT,
                agent_id TEXT,
                type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_requests (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                requires_approval INTEGER NOT NULL,
                result_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                run_id TEXT,
                payload_json TEXT NOT NULL,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_requests_task_key
            ON tool_requests(task_id, idempotency_key);

            CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_tool_requests_run_id ON tool_requests(run_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_run_id ON jobs(run_id);
            """
        )

    @staticmethod
    def _dumps(payload: Dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True)

    @staticmethod
    def _loads(payload: Optional[str]) -> Dict[str, Any]:
        if not payload:
            return {}
        return json.loads(payload)

    @staticmethod
    def _iso(dt: datetime) -> str:
        return dt.isoformat()

    @staticmethod
    def _dt(raw: str) -> datetime:
        return datetime.fromisoformat(raw)

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self.conn.execute(query, params)
            self.conn.commit()
            return cursor

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(query, params).fetchone()

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(query, params).fetchall()

    def _executescript(self, script: str) -> None:
        with self._lock:
            self.conn.executescript(script)
            self.conn.commit()

    def save_run(self, run: Run) -> None:
        self._execute(
            """
            INSERT INTO runs(id, objective, status, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                objective = excluded.objective,
                status = excluded.status,
                created_at = excluded.created_at
            """,
            (run.id, run.objective, run.status.value, self._iso(run.created_at)),
        )

    def get_run(self, run_id: str) -> Run:
        row = self._fetchone("SELECT * FROM runs WHERE id = ?", (run_id,))
        if row is None:
            raise KeyError(run_id)
        return Run(
            id=row["id"],
            objective=row["objective"],
            status=RunStatus(row["status"]),
            created_at=self._dt(row["created_at"]),
        )

    def list_runs(self) -> List[Run]:
        rows = self._fetchall("SELECT * FROM runs ORDER BY created_at")
        return [
            Run(
                id=row["id"],
                objective=row["objective"],
                status=RunStatus(row["status"]),
                created_at=self._dt(row["created_at"]),
            )
            for row in rows
        ]

    def update_run_status(self, run_id: str, status: RunStatus) -> None:
        self._execute("UPDATE runs SET status = ? WHERE id = ?", (status.value, run_id))

    def save_task(self, task: Task) -> None:
        self._execute(
            """
            INSERT INTO tasks(
                id, run_id, title, description, required_capability, parent_task_id,
                owner_agent_id, status, priority, dependencies_json, artifacts_json,
                budget_json, inputs_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                run_id = excluded.run_id,
                title = excluded.title,
                description = excluded.description,
                required_capability = excluded.required_capability,
                parent_task_id = excluded.parent_task_id,
                owner_agent_id = excluded.owner_agent_id,
                status = excluded.status,
                priority = excluded.priority,
                dependencies_json = excluded.dependencies_json,
                artifacts_json = excluded.artifacts_json,
                budget_json = excluded.budget_json,
                inputs_json = excluded.inputs_json,
                created_at = excluded.created_at
            """,
            (
                task.id,
                task.run_id,
                task.title,
                task.description,
                task.required_capability,
                task.parent_task_id,
                task.owner_agent_id,
                task.status.value,
                task.priority,
                self._dumps({"dependencies": task.dependencies}),
                self._dumps({"artifacts": task.artifacts}),
                self._dumps(asdict(task.budget)),
                self._dumps(task.inputs),
                self._iso(task.created_at),
            ),
        )

    def get_task(self, task_id: str) -> Task:
        row = self._fetchone("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, run_id: Optional[str] = None) -> List[Task]:
        if run_id is None:
            rows = self._fetchall("SELECT * FROM tasks ORDER BY created_at")
        else:
            rows = self._fetchall(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at", (run_id,)
            )
        return [self._task_from_row(row) for row in rows]

    def _task_from_row(self, row: sqlite3.Row) -> Task:
        dependencies = self._loads(row["dependencies_json"]).get("dependencies", [])
        artifacts = self._loads(row["artifacts_json"]).get("artifacts", [])
        budget_payload = self._loads(row["budget_json"])
        return Task(
            id=row["id"],
            run_id=row["run_id"],
            title=row["title"],
            description=row["description"],
            required_capability=row["required_capability"],
            parent_task_id=row["parent_task_id"],
            owner_agent_id=row["owner_agent_id"],
            status=TaskStatus(row["status"]),
            priority=row["priority"],
            dependencies=dependencies,
            artifacts=artifacts,
            budget=Budget(**budget_payload),
            inputs=self._loads(row["inputs_json"]),
            created_at=self._dt(row["created_at"]),
        )

    def save_artifact(self, artifact: Artifact) -> None:
        self._execute(
            """
            INSERT INTO artifacts(id, task_id, kind, summary, content_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                task_id = excluded.task_id,
                kind = excluded.kind,
                summary = excluded.summary,
                content_json = excluded.content_json,
                created_at = excluded.created_at
            """,
            (
                artifact.id,
                artifact.task_id,
                artifact.kind,
                artifact.summary,
                self._dumps(artifact.content),
                self._iso(artifact.created_at),
            ),
        )

    def list_artifacts(self, task_id: Optional[str] = None) -> List[Artifact]:
        if task_id is None:
            rows = self._fetchall("SELECT * FROM artifacts ORDER BY created_at")
        else:
            rows = self._fetchall(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at", (task_id,)
            )
        return [
            Artifact(
                id=row["id"],
                task_id=row["task_id"],
                kind=row["kind"],
                summary=row["summary"],
                content=self._loads(row["content_json"]),
                created_at=self._dt(row["created_at"]),
            )
            for row in rows
        ]

    def save_event(self, event: Event) -> None:
        self._execute(
            """
            INSERT OR REPLACE INTO events(id, run_id, task_id, agent_id, type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.run_id,
                event.task_id,
                event.agent_id,
                event.type,
                self._dumps(event.payload),
                self._iso(event.created_at),
            ),
        )

    def list_events(self, run_id: Optional[str] = None, limit: Optional[int] = None) -> List[Event]:
        query = "SELECT * FROM events"
        params: List[Any] = []
        if run_id is not None:
            query += " WHERE run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._fetchall(query, tuple(params))
        return [
            Event(
                id=row["id"],
                run_id=row["run_id"],
                type=row["type"],
                payload=self._loads(row["payload_json"]),
                task_id=row["task_id"],
                agent_id=row["agent_id"],
                created_at=self._dt(row["created_at"]),
            )
            for row in rows
        ]

    def save_tool_request(self, request: ToolRequest) -> None:
        self._execute(
            """
            INSERT INTO tool_requests(
                id, run_id, task_id, agent_id, tool_name, arguments_json, idempotency_key,
                status, requires_approval, result_json, error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                run_id = excluded.run_id,
                task_id = excluded.task_id,
                agent_id = excluded.agent_id,
                tool_name = excluded.tool_name,
                arguments_json = excluded.arguments_json,
                idempotency_key = excluded.idempotency_key,
                status = excluded.status,
                requires_approval = excluded.requires_approval,
                result_json = excluded.result_json,
                error = excluded.error,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                request.id,
                request.run_id,
                request.task_id,
                request.agent_id,
                request.tool_name,
                self._dumps(request.arguments),
                request.idempotency_key,
                request.status.value,
                1 if request.requires_approval else 0,
                self._dumps(request.result) if request.result is not None else None,
                request.error,
                self._iso(request.created_at),
                self._iso(request.updated_at),
            ),
        )

    def get_tool_request(self, request_id: str) -> ToolRequest:
        row = self._fetchone("SELECT * FROM tool_requests WHERE id = ?", (request_id,))
        if row is None:
            raise KeyError(request_id)
        return self._tool_request_from_row(row)

    def find_tool_request(self, task_id: str, idempotency_key: str) -> Optional[ToolRequest]:
        row = self._fetchone(
            "SELECT * FROM tool_requests WHERE task_id = ? AND idempotency_key = ?",
            (task_id, idempotency_key),
        )
        if row is None:
            return None
        return self._tool_request_from_row(row)

    def list_tool_requests(
        self,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[ToolRequestStatus] = None,
    ) -> List[ToolRequest]:
        query = "SELECT * FROM tool_requests WHERE 1=1"
        params: List[Any] = []
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        if task_id is not None:
            query += " AND task_id = ?"
            params.append(task_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at"
        rows = self._fetchall(query, tuple(params))
        return [self._tool_request_from_row(row) for row in rows]

    def update_tool_request(
        self,
        request_id: str,
        status: ToolRequestStatus,
        *,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        updated_at: Optional[datetime] = None,
    ) -> ToolRequest:
        now = updated_at or utc_now()
        self._execute(
            """
            UPDATE tool_requests
            SET status = ?, result_json = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status.value,
                self._dumps(result) if result is not None else None,
                error,
                self._iso(now),
                request_id,
            ),
        )
        return self.get_tool_request(request_id)

    def _tool_request_from_row(self, row: sqlite3.Row) -> ToolRequest:
        result_payload = row["result_json"]
        return ToolRequest(
            id=row["id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            tool_name=row["tool_name"],
            arguments=self._loads(row["arguments_json"]),
            idempotency_key=row["idempotency_key"],
            status=ToolRequestStatus(row["status"]),
            requires_approval=bool(row["requires_approval"]),
            result=self._loads(result_payload) if result_payload else None,
            error=row["error"],
            created_at=self._dt(row["created_at"]),
            updated_at=self._dt(row["updated_at"]),
        )

    def save_job(self, job: OperationJob) -> None:
        self._execute(
            """
            INSERT INTO jobs(id, kind, status, operator_id, run_id, payload_json, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                status = excluded.status,
                operator_id = excluded.operator_id,
                run_id = excluded.run_id,
                payload_json = excluded.payload_json,
                error = excluded.error,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                job.id,
                job.kind,
                job.status.value,
                job.operator_id,
                job.run_id,
                self._dumps(job.payload),
                job.error,
                self._iso(job.created_at),
                self._iso(job.updated_at),
            ),
        )

    def get_job(self, job_id: str) -> OperationJob:
        row = self._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise KeyError(job_id)
        return self._job_from_row(row)

    def list_jobs(
        self,
        *,
        run_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: Optional[int] = None,
    ) -> List[OperationJob]:
        query = "SELECT * FROM jobs WHERE 1=1"
        params: List[Any] = []
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._fetchall(query, tuple(params))
        return [self._job_from_row(row) for row in rows]

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
        updated_at: Optional[datetime] = None,
    ) -> OperationJob:
        current = self.get_job(job_id)
        next_payload = payload if payload is not None else current.payload
        next_run_id = current.run_id if run_id is None else run_id
        now = updated_at or utc_now()
        self._execute(
            """
            UPDATE jobs
            SET status = ?, payload_json = ?, run_id = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status.value,
                self._dumps(next_payload),
                next_run_id,
                error,
                self._iso(now),
                job_id,
            ),
        )
        return self.get_job(job_id)

    def _job_from_row(self, row: sqlite3.Row) -> OperationJob:
        return OperationJob(
            id=row["id"],
            kind=row["kind"],
            status=JobStatus(row["status"]),
            operator_id=row["operator_id"],
            run_id=row["run_id"],
            payload=self._loads(row["payload_json"]),
            error=row["error"],
            created_at=self._dt(row["created_at"]),
            updated_at=self._dt(row["updated_at"]),
        )
