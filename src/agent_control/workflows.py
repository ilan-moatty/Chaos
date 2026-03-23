from __future__ import annotations

from agent_control.models import Run
from agent_control.supervisor import Supervisor, build_root_task


async def prepare_demo_run(supervisor: Supervisor) -> Run:
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
    return run


async def start_demo_run(supervisor: Supervisor) -> Run:
    run = await prepare_demo_run(supervisor)
    await supervisor.run_until_stable(run)
    return run


async def prepare_release_brief_run(supervisor: Supervisor) -> Run:
    run = await supervisor.submit_run("Prepare a release brief for the operator team.")

    research_task = build_root_task(
        run_id=run.id,
        title="Research release context",
        description="Collect the main points that should appear in the release brief.",
        capability="research",
        priority=10,
    )
    execution_task = build_root_task(
        run_id=run.id,
        title="Draft and publish release brief",
        description="Prepare the release brief and request publication once ready.",
        capability="execution",
        priority=20,
    )
    execution_task.inputs["spawn_review"] = True
    execution_task.inputs["request_publish_approval"] = True
    execution_task.inputs["publish_channel"] = "release-ops"

    await supervisor.add_task(research_task)
    await supervisor.add_task(execution_task)
    return run


async def start_release_brief_run(supervisor: Supervisor) -> Run:
    run = await prepare_release_brief_run(supervisor)
    await supervisor.run_until_stable(run)
    return run
