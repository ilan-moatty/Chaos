from __future__ import annotations

import asyncio
from pathlib import Path

from agent_control.models import ToolRequestStatus
from agent_control.runtime import approve_tool_request, build_runtime
from agent_control.workflows import start_demo_run


async def main() -> None:
    db_path = Path("agent-control-demo.db")
    if db_path.exists():
        db_path.unlink()
    supervisor, store, event_bus = build_runtime(str(db_path))

    run = await start_demo_run(supervisor)
    artifacts = []
    print(f"=== First Pass ===\nrun={run.id} status={store.get_run(run.id).status.value}")
    pending = store.list_tool_requests(run_id=run.id, status=ToolRequestStatus.PENDING_APPROVAL)
    for request in pending:
        print(f"pending approval: {request.id} tool={request.tool_name} args={request.arguments}")
        approve_tool_request(store, request.id)

    resumed_run = await supervisor.resume_run(run.id)
    artifacts.extend(await supervisor.run_until_stable(resumed_run))

    print("=== Event Timeline ===")
    for event in store.list_events(run.id):
        task_part = f" task={event.task_id}" if event.task_id else ""
        agent_part = f" agent={event.agent_id}" if event.agent_id else ""
        print(f"{event.type}{task_part}{agent_part} payload={event.payload}")

    print("\n=== Artifacts ===")
    for artifact in store.list_artifacts():
        print(f"{artifact.kind}: {artifact.summary}")

    store.close()


if __name__ == "__main__":
    asyncio.run(main())
