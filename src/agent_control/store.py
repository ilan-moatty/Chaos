from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_control.models import (
    Artifact,
    Budget,
    Event,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    ToolRequest,
    ToolRequestStatus,
)


class SqliteStore:
    """Durable storage for runs, tasks, artifacts, events, and tool requests."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
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

            CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_requests_task_key
            ON tool_requests(task_id, idempotency_key);

            CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id);
            CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id);
            CREATE INDEX IF NOT EXISTS idx_tool_requests_run_id ON tool_requests(run_id);
            """
        )
        self.conn.commit()

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

    def save_run(self, run: Run) -> None:
        self.conn.execute(
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
        self.conn.commit()

    def get_run(self, run_id: str) -> Run:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return Run(
            id=row["id"],
            objective=row["objective"],
            status=RunStatus(row["status"]),
            created_at=self._dt(row["created_at"]),
        )

    def list_runs(self) -> List[Run]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY created_at").fetchall()
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
        self.conn.execute("UPDATE runs SET status = ? WHERE id = ?", (status.value, run_id))
        self.conn.commit()

    def save_task(self, task: Task) -> None:
        self.conn.execute(
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
        self.conn.commit()

    def get_task(self, task_id: str) -> Task:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, run_id: Optional[str] = None) -> List[Task]:
        if run_id is None:
            rows = self.conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at", (run_id,)
            ).fetchall()
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
        self.conn.execute(
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
        self.conn.commit()

    def list_artifacts(self, task_id: Optional[str] = None) -> List[Artifact]:
        if task_id is None:
            rows = self.conn.execute("SELECT * FROM artifacts ORDER BY created_at").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at", (task_id,)
            ).fetchall()
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
        self.conn.execute(
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
        self.conn.commit()

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
        rows = self.conn.execute(query, params).fetchall()
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
        self.conn.execute(
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
        self.conn.commit()

    def get_tool_request(self, request_id: str) -> ToolRequest:
        row = self.conn.execute("SELECT * FROM tool_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        return self._tool_request_from_row(row)

    def find_tool_request(self, task_id: str, idempotency_key: str) -> Optional[ToolRequest]:
        row = self.conn.execute(
            "SELECT * FROM tool_requests WHERE task_id = ? AND idempotency_key = ?",
            (task_id, idempotency_key),
        ).fetchone()
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
        rows = self.conn.execute(query, params).fetchall()
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
        now = updated_at or datetime.utcnow()
        self.conn.execute(
            """
            UPDATE tool_requests
            SET status = ?, result_json = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status.value,
                self._dumps(result) if result is not None else None,
                error,
                now.isoformat(),
                request_id,
            ),
        )
        self.conn.commit()
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
