from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import time
import threading
from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from agent_control import __version__
from agent_control.background_jobs import BackgroundJobRunner
from agent_control.config import ChaosSettings
from agent_control.models import (
    Artifact,
    Event,
    JobStatus,
    OperationJob,
    Run,
    Task,
    ToolRequest,
    ToolRequestStatus,
    new_id,
    utc_now,
)
from agent_control.runtime import approve_tool_request, build_runtime, deny_tool_request
from agent_control.store import SqliteStore
from agent_control.workflows import prepare_demo_run, prepare_release_brief_run


def iso(dt: datetime) -> str:
    return dt.isoformat()


def serialize_run(run: Run) -> Dict[str, Any]:
    return {
        "id": run.id,
        "objective": run.objective,
        "status": run.status.value,
        "created_at": iso(run.created_at),
    }


def serialize_task(task: Task) -> Dict[str, Any]:
    return {
        "id": task.id,
        "run_id": task.run_id,
        "title": task.title,
        "description": task.description,
        "required_capability": task.required_capability,
        "parent_task_id": task.parent_task_id,
        "owner_agent_id": task.owner_agent_id,
        "status": task.status.value,
        "priority": task.priority,
        "dependencies": list(task.dependencies),
        "artifacts": list(task.artifacts),
        "budget": asdict(task.budget),
        "inputs": dict(task.inputs),
        "created_at": iso(task.created_at),
    }


def serialize_event(event: Event) -> Dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "task_id": event.task_id,
        "agent_id": event.agent_id,
        "type": event.type,
        "payload": event.payload,
        "created_at": iso(event.created_at),
    }


def serialize_artifact(artifact: Artifact) -> Dict[str, Any]:
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "kind": artifact.kind,
        "summary": artifact.summary,
        "content": artifact.content,
        "created_at": iso(artifact.created_at),
    }


def serialize_tool_request(tool_request: ToolRequest) -> Dict[str, Any]:
    return {
        "id": tool_request.id,
        "run_id": tool_request.run_id,
        "task_id": tool_request.task_id,
        "agent_id": tool_request.agent_id,
        "tool_name": tool_request.tool_name,
        "arguments": tool_request.arguments,
        "idempotency_key": tool_request.idempotency_key,
        "status": tool_request.status.value,
        "requires_approval": tool_request.requires_approval,
        "result": tool_request.result,
        "error": tool_request.error,
        "created_at": iso(tool_request.created_at),
        "updated_at": iso(tool_request.updated_at),
    }


def serialize_job(job: OperationJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status.value,
        "operator_id": job.operator_id,
        "run_id": job.run_id,
        "payload": job.payload,
        "error": job.error,
        "created_at": iso(job.created_at),
        "updated_at": iso(job.updated_at),
    }


def build_run_summary(store: SqliteStore, run: Run) -> Dict[str, Any]:
    tasks = store.list_tasks(run.id)
    approvals = store.list_tool_requests(run_id=run.id, status=ToolRequestStatus.PENDING_APPROVAL)
    completed = sum(task.status.value == "COMPLETED" for task in tasks)
    return {
        **serialize_run(run),
        "task_count": len(tasks),
        "completed_task_count": completed,
        "pending_approval_count": len(approvals),
    }


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class ChaosWebApp:
    def __init__(self, db_path: str, settings: Optional[ChaosSettings] = None) -> None:
        self.settings = settings or ChaosSettings(db_path=db_path)
        self.supervisor, self.store, self.event_bus = build_runtime(db_path)
        self.action_lock = threading.Lock()
        self.started_at = utc_now()
        self.job_runner = BackgroundJobRunner(self.store)
        ui_root = Path(__file__).parent / "ui"
        self.index_html = (ui_root / "templates" / "index.html").read_text(encoding="utf-8")
        self.styles_css = (ui_root / "static" / "styles.css").read_text(encoding="utf-8")
        self.app_js = (ui_root / "static" / "app.js").read_text(encoding="utf-8")
        self.job_runner.register("start_demo_run", self._handle_start_run_job)
        self.job_runner.register("start_release_brief_run", self._handle_start_run_job)
        self.job_runner.register("resume_run", self._handle_resume_run_job)

    def close(self) -> None:
        self.job_runner.close()
        self.store.close()

    def run_async(self, coro):
        with self.action_lock:
            return asyncio.run(coro)

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        run = self.store.get_run(run_id)
        tasks = self.store.list_tasks(run_id)
        artifacts: List[Artifact] = []
        for task in tasks:
            artifacts.extend(self.store.list_artifacts(task.id))
        events = self.store.list_events(run_id)
        tool_requests = self.store.list_tool_requests(run_id=run_id)
        jobs = self.store.list_jobs(run_id=run_id, limit=10)
        return {
            "run": build_run_summary(self.store, run),
            "tasks": [serialize_task(task) for task in tasks],
            "events": [serialize_event(event) for event in events],
            "artifacts": [serialize_artifact(artifact) for artifact in artifacts],
            "tool_requests": [serialize_tool_request(tool_request) for tool_request in tool_requests],
            "jobs": [serialize_job(job) for job in jobs],
            "pending_task_ids": [
                task.id
                for task in tasks
                if task.status.value not in {"COMPLETED", "FAILED", "CANCELLED"}
            ],
            "task_ids": sorted(task.id for task in tasks),
        }

    def dashboard(self) -> Dict[str, Any]:
        runs = [build_run_summary(self.store, run) for run in reversed(self.store.list_runs())]
        jobs = self.store.list_jobs(limit=12)
        approvals = [
            serialize_tool_request(request_item)
            for request_item in self.store.list_tool_requests(status=ToolRequestStatus.PENDING_APPROVAL)
        ]
        stats = {
            "run_count": len(runs),
            "active_count": sum(run["status"] == "ACTIVE" for run in runs),
            "paused_count": sum(run["status"] == "PAUSED" for run in runs),
            "approval_count": len(approvals),
            "job_count": len([job for job in jobs if job.status in {JobStatus.PENDING, JobStatus.RUNNING}]),
        }
        return {"runs": runs, "approvals": approvals, "jobs": [serialize_job(job) for job in jobs], "stats": stats}

    def health(self) -> Dict[str, Any]:
        db_available = True
        try:
            self.store.conn.execute("SELECT 1").fetchone()
        except Exception:
            db_available = False
        return {
            "ok": db_available,
            "status": "ok" if db_available else "degraded",
            "environment": self.settings.environment,
            "version": self.settings.app_version,
            "started_at": iso(self.started_at),
            "uptime_seconds": round((utc_now() - self.started_at).total_seconds(), 3),
            "storage": {"backend": "sqlite", "available": db_available},
            "auth": {"required": self.settings.api_auth_enabled},
            "background_jobs": {
                "backend": "in-process",
                "running": len(self.store.list_jobs(status=JobStatus.RUNNING)),
                "pending": len(self.store.list_jobs(status=JobStatus.PENDING)),
            },
        }

    def metadata(self) -> Dict[str, Any]:
        return {
            "product": "Chaos",
            "version": self.settings.app_version,
            "environment": self.settings.environment,
            "started_at": iso(self.started_at),
            "auth": {
                "required": self.settings.api_auth_enabled,
                "operator_header": self.settings.operator_header,
                "authorization_header": "Authorization: Bearer <token>",
            },
            "features": {
                "request_logging": self.settings.request_logging_enabled,
                "storage_backend": "sqlite",
                "background_jobs": True,
                "web_ui": True,
                "approval_flow": True,
            },
        }

    def create_demo_run(self, operator_id: str) -> Dict[str, Any]:
        run = self.run_async(prepare_demo_run(self.supervisor))
        job = OperationJob(
            id=new_id("job"),
            kind="start_demo_run",
            status=JobStatus.PENDING,
            operator_id=operator_id,
            run_id=run.id,
            payload={"workflow": "demo", "run_id": run.id},
        )
        self.job_runner.submit(job)
        self._record_operator_event(
            run.id,
            operator_id,
            "run.demo_queued",
            {"workflow": "demo", "objective": run.objective},
        )
        detail = self.run_detail(run.id)
        detail["job"] = serialize_job(self.store.get_job(job.id))
        return detail

    def create_release_brief(self, operator_id: str) -> Dict[str, Any]:
        run = self.run_async(prepare_release_brief_run(self.supervisor))
        job = OperationJob(
            id=new_id("job"),
            kind="start_release_brief_run",
            status=JobStatus.PENDING,
            operator_id=operator_id,
            run_id=run.id,
            payload={"workflow": "release-brief", "run_id": run.id},
        )
        self.job_runner.submit(job)
        self._record_operator_event(
            run.id,
            operator_id,
            "run.release_brief_queued",
            {"workflow": "release-brief", "objective": run.objective},
        )
        detail = self.run_detail(run.id)
        detail["job"] = serialize_job(self.store.get_job(job.id))
        return detail

    def resume_run(self, run_id: str, operator_id: str) -> Dict[str, Any]:
        job = OperationJob(
            id=new_id("job"),
            kind="resume_run",
            status=JobStatus.PENDING,
            operator_id=operator_id,
            run_id=run_id,
            payload={"run_id": run_id},
        )
        self.job_runner.submit(job)
        self._record_operator_event(run_id, operator_id, "run.resume_queued", {})
        detail = self.run_detail(run_id)
        detail["job"] = serialize_job(self.store.get_job(job.id))
        return detail

    def approve(self, request_id: str, operator_id: str) -> Dict[str, Any]:
        with self.action_lock:
            approve_tool_request(self.store, request_id)
        request_item = self.store.get_tool_request(request_id)
        self._record_operator_event(
            request_item.run_id,
            operator_id,
            "tool_request.approved",
            {"tool_request_id": request_item.id, "tool_name": request_item.tool_name},
        )
        return {
            "tool_request": serialize_tool_request(request_item),
            "run": build_run_summary(self.store, self.store.get_run(request_item.run_id)),
        }

    def deny(self, request_id: str, reason: str, operator_id: str) -> Dict[str, Any]:
        with self.action_lock:
            deny_tool_request(self.store, request_id, reason)
        request_item = self.store.get_tool_request(request_id)
        self._record_operator_event(
            request_item.run_id,
            operator_id,
            "tool_request.denied",
            {
                "tool_request_id": request_item.id,
                "tool_name": request_item.tool_name,
                "reason": reason,
            },
        )
        return {
            "tool_request": serialize_tool_request(request_item),
            "run": build_run_summary(self.store, self.store.get_run(request_item.run_id)),
        }

    def _record_operator_event(
        self,
        run_id: str,
        operator_id: str,
        action: str,
        payload: Dict[str, Any],
    ) -> None:
        self.run_async(
            self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=run_id,
                    type="operator.action",
                    payload={"action": action, "operator_id": operator_id, **payload},
                )
            )
        )

    def _record_job_event(self, job: OperationJob, event_type: str, payload: Dict[str, Any]) -> None:
        if not job.run_id:
            return
        self.run_async(
            self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=job.run_id,
                    type=event_type,
                    payload={"job_id": job.id, "job_kind": job.kind, **payload},
                )
            )
        )

    def _handle_start_run_job(self, job: OperationJob) -> None:
        if not job.run_id:
            raise ValueError("start job is missing run_id")
        self._record_job_event(job, "job.started", {"operator_id": job.operator_id})
        run = self.store.get_run(job.run_id)
        self.run_async(self.supervisor.run_until_stable(run))
        self._record_job_event(job, "job.completed", {"operator_id": job.operator_id})

    def _handle_resume_run_job(self, job: OperationJob) -> None:
        if not job.run_id:
            raise ValueError("resume job is missing run_id")
        self._record_job_event(job, "job.started", {"operator_id": job.operator_id})
        run = self.run_async(self.supervisor.resume_run(job.run_id))
        self.run_async(self.supervisor.run_until_stable(run))
        self._record_job_event(job, "job.completed", {"operator_id": job.operator_id})

    def _operator_id(self, headers: Dict[str, str]) -> str:
        return (
            headers.get(self.settings.operator_header)
            or headers.get("X-Operator-Id")
            or ("token-operator" if self.settings.api_auth_enabled else "local-operator")
        )

    def _is_authorized(self, headers: Dict[str, str]) -> bool:
        if not self.settings.api_auth_enabled:
            return True
        auth_value = headers.get("Authorization", "")
        if auth_value.startswith("Bearer "):
            token = auth_value[7:].strip()
            return hmac.compare_digest(token, self.settings.api_token or "")
        api_key = headers.get("X-API-Key", "")
        if api_key:
            return hmac.compare_digest(api_key, self.settings.api_token or "")
        return False

    def _is_public_route(self, path: str) -> bool:
        return path in {"/", "/static/styles.css", "/static/app.js", "/api/health", "/api/meta"}

    def _log_request(
        self,
        method: str,
        path: str,
        status: HTTPStatus,
        started_monotonic: float,
        operator_id: Optional[str],
    ) -> None:
        if not self.settings.request_logging_enabled:
            return
        payload = {
            "ts": iso(utc_now()),
            "method": method,
            "path": path,
            "status": status.value,
            "duration_ms": round((time.monotonic() - started_monotonic) * 1000, 2),
            "operator_id": operator_id,
            "auth_required": self.settings.api_auth_enabled,
        }
        print(json.dumps(payload, sort_keys=True))

    def dispatch(
        self,
        method: str,
        path: str,
        *,
        body: Dict[str, Any] | None = None,
        headers: Dict[str, str] | None = None,
    ) -> Tuple[HTTPStatus, str, bytes]:
        parsed = urlparse(path)
        parts = [part for part in parsed.path.split("/") if part]
        body = body or {}
        headers = headers or {}
        started_monotonic = time.monotonic()
        operator_id = self._operator_id(headers) if parsed.path.startswith("/api/") else None
        if parsed.path.startswith("/api/") and not self._is_public_route(parsed.path):
            if not self._is_authorized(headers):
                status, content_type, response_body = self._json_response(
                    HTTPStatus.UNAUTHORIZED,
                    {
                        "error": "Unauthorized.",
                        "hint": "Provide Authorization: Bearer <token> or X-API-Key.",
                    },
                )
                self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                return status, content_type, response_body
        try:
            if method == "GET":
                if parsed.path == "/":
                    status, content_type, response_body = (
                        HTTPStatus.OK,
                        "text/html; charset=utf-8",
                        self.index_html.encode("utf-8"),
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parsed.path == "/static/styles.css":
                    status, content_type, response_body = (
                        HTTPStatus.OK,
                        "text/css; charset=utf-8",
                        self.styles_css.encode("utf-8"),
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parsed.path == "/static/app.js":
                    status, content_type, response_body = (
                        HTTPStatus.OK,
                        "application/javascript; charset=utf-8",
                        self.app_js.encode("utf-8"),
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parsed.path == "/api/health":
                    status, content_type, response_body = self._json_response(HTTPStatus.OK, self.health())
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parsed.path == "/api/meta":
                    status, content_type, response_body = self._json_response(HTTPStatus.OK, self.metadata())
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parsed.path == "/api/dashboard":
                    status, content_type, response_body = self._json_response(HTTPStatus.OK, self.dashboard())
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parts == ["api", "jobs"]:
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.OK,
                        {"jobs": [serialize_job(job) for job in self.store.list_jobs(limit=50)]},
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if len(parts) == 3 and parts[0] == "api" and parts[1] == "jobs":
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.OK, {"job": serialize_job(self.store.get_job(parts[2]))}
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if len(parts) == 3 and parts[0] == "api" and parts[1] == "runs":
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.OK, self.run_detail(parts[2])
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
            if method == "POST":
                if parts == ["api", "runs", "demo"]:
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.ACCEPTED, self.create_demo_run(operator_id or "unknown")
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if parts == ["api", "runs", "release-brief"]:
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.ACCEPTED, self.create_release_brief(operator_id or "unknown")
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if len(parts) == 4 and parts[0] == "api" and parts[1] == "runs" and parts[3] == "resume":
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.ACCEPTED, self.resume_run(parts[2], operator_id or "unknown")
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if (
                    len(parts) == 4
                    and parts[0] == "api"
                    and parts[1] == "tool-requests"
                    and parts[3] == "approve"
                ):
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.OK, self.approve(parts[2], operator_id or "unknown")
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
                if (
                    len(parts) == 4
                    and parts[0] == "api"
                    and parts[1] == "tool-requests"
                    and parts[3] == "deny"
                ):
                    status, content_type, response_body = self._json_response(
                        HTTPStatus.OK,
                        self.deny(
                            parts[2],
                            body.get("reason", "Denied by operator."),
                            operator_id or "unknown",
                        ),
                    )
                    self._log_request(method, parsed.path, status, started_monotonic, operator_id)
                    return status, content_type, response_body
        except KeyError:
            status, content_type, response_body = self._json_response(
                HTTPStatus.NOT_FOUND, {"error": "Resource not found."}
            )
            self._log_request(method, parsed.path, status, started_monotonic, operator_id)
            return status, content_type, response_body
        except Exception as exc:
            status, content_type, response_body = self._json_response(
                HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)}
            )
            self._log_request(method, parsed.path, status, started_monotonic, operator_id)
            return status, content_type, response_body
        status, content_type, response_body = self._json_response(
            HTTPStatus.NOT_FOUND, {"error": "Route not found."}
        )
        self._log_request(method, parsed.path, status, started_monotonic, operator_id)
        return status, content_type, response_body

    @staticmethod
    def _json_response(status: HTTPStatus, payload: Dict[str, Any]) -> Tuple[HTTPStatus, str, bytes]:
        return status, "application/json; charset=utf-8", json.dumps(payload).encode("utf-8")


def create_handler(app: ChaosWebApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ChaosHTTP/0.1"

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if self.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            status, content_type, response_body = app.dispatch(
                "GET", self.path, headers={key: value for key, value in self.headers.items()}
            )
            self._send(status, content_type, response_body)

        def do_POST(self) -> None:
            status, content_type, response_body = app.dispatch(
                "POST",
                self.path,
                body=self._read_json(),
                headers={key: value for key, value in self.headers.items()},
            )
            self._send(status, content_type, response_body)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def create_server(settings: ChaosSettings) -> Tuple[ThreadingHTTPServer, ChaosWebApp]:
    app = ChaosWebApp(settings.db_path, settings=settings)
    handler = create_handler(app)
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    return server, app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Chaos operator dashboard.")
    defaults = ChaosSettings.from_env()
    parser.add_argument("--db", default=defaults.db_path, help="Path to the SQLite state database.")
    parser.add_argument("--host", default=defaults.host)
    parser.add_argument("--port", default=defaults.port, type=int)
    parser.add_argument("--environment", default=defaults.environment)
    parser.add_argument("--api-token", default=defaults.api_token)
    parser.add_argument("--operator-header", default=defaults.operator_header)
    parser.add_argument(
        "--request-logging",
        action="store_true",
        default=defaults.request_logging_enabled,
        help="Emit one JSON log line per HTTP request.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = ChaosSettings(
        db_path=str(Path(args.db)),
        host=args.host,
        port=args.port,
        environment=args.environment,
        api_token=args.api_token,
        operator_header=args.operator_header,
        request_logging_enabled=args.request_logging,
        app_version=__version__,
    )
    server, app = create_server(settings)
    auth_note = " (API auth enabled)" if settings.api_auth_enabled else ""
    print(f"Chaos Control Room running on http://{settings.host}:{settings.port}{auth_note}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
