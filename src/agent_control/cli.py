from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from agent_control.models import ToolRequestStatus
from agent_control.runtime import approve_tool_request, build_runtime, deny_tool_request
from agent_control.store import SqliteStore
from agent_control.supervisor import build_root_task


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operator CLI for the multi-agent control plane.")
    parser.add_argument("--db", default="agent-control.db", help="Path to the SQLite state database.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("demo", help="Create a demo run and execute until paused or completed.")

    status = subparsers.add_parser("status", help="Show runs, tasks, and pending approvals.")
    status.add_argument("--run-id", help="Optional run ID filter.")

    approvals = subparsers.add_parser("approvals", help="List pending approval requests.")
    approvals.add_argument("--run-id", help="Optional run ID filter.")

    approve = subparsers.add_parser("approve", help="Approve a tool request.")
    approve.add_argument("request_id")

    deny = subparsers.add_parser("deny", help="Deny a tool request.")
    deny.add_argument("request_id")
    deny.add_argument("--reason", default="Denied by operator.")

    resume = subparsers.add_parser("resume", help="Resume a paused run after approvals.")
    resume.add_argument("run_id")

    return parser


async def command_demo(db_path: str) -> None:
    supervisor, store, _ = build_runtime(db_path)
    run = await supervisor.submit_run("Design a manageable multi-agent coordination system.")

    research_task = build_root_task(
        run_id=run.id,
        title="Research coordination patterns",
        description="Gather patterns for multi-agent orchestration and human control.",
        capability="research",
        priority=10,
    )
    execution_task = build_root_task(
        run_id=run.id,
        title="Design runtime kernel",
        description="Define supervisor, task board, event log, and tool gateway.",
        capability="execution",
        priority=20,
    )
    execution_task.inputs["spawn_review"] = True
    execution_task.inputs["request_publish_approval"] = True
    execution_task.inputs["publish_channel"] = "operator"

    await supervisor.add_task(research_task)
    await supervisor.add_task(execution_task)
    await supervisor.run_until_stable(run)

    print(f"run_id={run.id} status={store.get_run(run.id).status.value}")
    pending = store.list_tool_requests(run_id=run.id, status=ToolRequestStatus.PENDING_APPROVAL)
    if pending:
        print("pending_approvals:")
        for request in pending:
            print(f"  {request.id} tool={request.tool_name} args={request.arguments}")
    store.close()


def command_status(db_path: str, run_id: Optional[str]) -> None:
    store = SqliteStore(db_path)
    runs = [store.get_run(run_id)] if run_id else store.list_runs()
    for run in runs:
        print(f"run {run.id} status={run.status.value} objective={run.objective}")
        for task in store.list_tasks(run.id):
            print(
                f"  task {task.id} status={task.status.value} capability={task.required_capability} owner={task.owner_agent_id}"
            )
    pending = store.list_tool_requests(run_id=run_id, status=ToolRequestStatus.PENDING_APPROVAL)
    if pending:
        print("pending approvals:")
        for request in pending:
            print(f"  {request.id} run={request.run_id} task={request.task_id} tool={request.tool_name}")
    store.close()


def command_approvals(db_path: str, run_id: Optional[str]) -> None:
    store = SqliteStore(db_path)
    pending = store.list_tool_requests(run_id=run_id, status=ToolRequestStatus.PENDING_APPROVAL)
    if not pending:
        print("No pending approvals.")
    for request in pending:
        print(f"{request.id} run={request.run_id} task={request.task_id} tool={request.tool_name} args={request.arguments}")
    store.close()


def command_approve(db_path: str, request_id: str) -> None:
    store = SqliteStore(db_path)
    approve_tool_request(store, request_id)
    request = store.get_tool_request(request_id)
    print(f"approved {request.id} for run {request.run_id}")
    store.close()


def command_deny(db_path: str, request_id: str, reason: str) -> None:
    store = SqliteStore(db_path)
    deny_tool_request(store, request_id, reason)
    request = store.get_tool_request(request_id)
    print(f"denied {request.id} for run {request.run_id}")
    store.close()


async def command_resume(db_path: str, run_id: str) -> None:
    supervisor, store, _ = build_runtime(db_path)
    run = await supervisor.resume_run(run_id)
    await supervisor.run_until_stable(run)
    refreshed = store.get_run(run_id)
    print(f"run_id={refreshed.id} status={refreshed.status.value}")
    store.close()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    db_path = str(Path(args.db))

    if args.command == "demo":
        asyncio.run(command_demo(db_path))
    elif args.command == "status":
        command_status(db_path, args.run_id)
    elif args.command == "approvals":
        command_approvals(db_path, args.run_id)
    elif args.command == "approve":
        command_approve(db_path, args.request_id)
    elif args.command == "deny":
        command_deny(db_path, args.request_id, args.reason)
    elif args.command == "resume":
        asyncio.run(command_resume(db_path, args.run_id))


if __name__ == "__main__":
    main()
