from __future__ import annotations

import asyncio
from pathlib import Path

from agent_control.models import ToolRequestStatus
from agent_control.runtime import approve_tool_request, build_runtime
from agent_control.supervisor import build_root_task


async def main() -> None:
    db_path = Path("agent-control-demo.db")
    if db_path.exists():
        db_path.unlink()
    supervisor, store, event_bus = build_runtime(str(db_path))

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

    artifacts = await supervisor.run_until_stable(run)
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
