from __future__ import annotations

import asyncio
from typing import List, Optional

from agent_control.agents import AgentRegistry
from agent_control.event_bus import EventBus
from agent_control.models import Artifact, Event, Run, RunStatus, Task, TaskStatus, ToolRequestStatus, new_id
from agent_control.store import SqliteStore
from agent_control.task_board import TaskBoard
from agent_control.tool_gateway import ToolGateway


class Supervisor:
    """Coordinates tasks, agents, and event emission."""

    def __init__(
        self,
        event_bus: EventBus,
        task_board: TaskBoard,
        agents: AgentRegistry,
        store: SqliteStore,
        tool_gateway: ToolGateway,
    ) -> None:
        self.event_bus = event_bus
        self.task_board = task_board
        self.agents = agents
        self.store = store
        self.tool_gateway = tool_gateway

    async def submit_run(self, objective: str) -> Run:
        run = Run(id=new_id("run"), objective=objective)
        self.store.save_run(run)
        await self.event_bus.publish(
            Event(id=new_id("evt"), run_id=run.id, type="run.created", payload={"objective": objective})
        )
        return run

    async def add_task(self, task: Task) -> None:
        self.task_board.add(task)
        await self.event_bus.publish(
            Event(
                id=new_id("evt"),
                run_id=task.run_id,
                task_id=task.id,
                type="task.created",
                payload={"title": task.title, "capability": task.required_capability},
            )
        )
        if self.task_board.dependencies_completed(task):
            task.status = TaskStatus.READY
            await self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=task.run_id,
                    task_id=task.id,
                    type="task.ready",
                    payload={"title": task.title},
                )
            )

    async def resume_run(self, run_id: str) -> Run:
        run = self.store.get_run(run_id)
        self.task_board.load_tasks(self.store.list_tasks(run_id))
        for task in self.task_board.tasks_for_run(run_id):
            requests = self.store.list_tool_requests(task_id=task.id)
            if task.status is TaskStatus.WAITING_FOR_APPROVAL and any(
                request.status is ToolRequestStatus.APPROVED for request in requests
            ):
                self.task_board.update_status(task.id, TaskStatus.READY)
            if task.status is TaskStatus.WAITING_FOR_APPROVAL and any(
                request.status is ToolRequestStatus.DENIED for request in requests
            ):
                self.task_board.update_status(task.id, TaskStatus.FAILED)
        run.status = RunStatus.ACTIVE
        self.store.save_run(run)
        await self.event_bus.publish(
            Event(id=new_id("evt"), run_id=run.id, type="run.resumed", payload={"run_id": run.id})
        )
        return run

    async def run_until_stable(self, run: Run) -> List[Artifact]:
        artifacts: List[Artifact] = []
        while True:
            ready_tasks = sorted(self.task_board.ready_tasks(run.id), key=lambda task: task.priority)
            if not ready_tasks:
                tasks = self.task_board.tasks_for_run(run.id)
                if tasks and all(task.status is TaskStatus.COMPLETED for task in tasks):
                    run.status = RunStatus.COMPLETED
                    self.store.save_run(run)
                    break
                if any(task.status is TaskStatus.WAITING_FOR_APPROVAL for task in tasks):
                    run.status = RunStatus.PAUSED
                    self.store.save_run(run)
                    await self.event_bus.publish(
                        Event(
                            id=new_id("evt"),
                            run_id=run.id,
                            type="run.paused",
                            payload={"reason": "Waiting for approval"},
                        )
                    )
                    return artifacts
                if any(task.status is TaskStatus.BLOCKED for task in tasks):
                    run.status = RunStatus.PAUSED
                    self.store.save_run(run)
                    await self.event_bus.publish(
                        Event(
                            id=new_id("evt"),
                            run_id=run.id,
                            type="run.paused",
                            payload={"reason": "Blocked tasks remain"},
                        )
                    )
                    return artifacts
                await asyncio.sleep(0.01)
                continue

            await asyncio.gather(*(self._dispatch(task, artifacts) for task in ready_tasks))

        await self.event_bus.publish(
            Event(
                id=new_id("evt"),
                run_id=run.id,
                type="run.completed",
                payload={"artifact_count": len(artifacts)},
            )
        )
        return artifacts

    async def _dispatch(self, task: Task, artifacts: List[Artifact]) -> None:
        if task.status is not TaskStatus.READY:
            return

        candidate_agents = self.agents.agents_for_capability(task.required_capability)
        if not candidate_agents:
            self.task_board.update_status(task.id, TaskStatus.BLOCKED)
            await self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=task.run_id,
                    task_id=task.id,
                    type="task.blocked",
                    payload={"reason": f"No available agent for capability {task.required_capability}"},
                )
            )
            return

        agent = candidate_agents[0]
        self.task_board.assign(task.id, agent.spec.id)
        self.task_board.update_status(task.id, TaskStatus.RUNNING)
        await self.event_bus.publish(
            Event(
                id=new_id("evt"),
                run_id=task.run_id,
                task_id=task.id,
                agent_id=agent.spec.id,
                type="agent.assigned",
                payload={"agent": agent.spec.name},
            )
        )
        await self.event_bus.publish(
            Event(
                id=new_id("evt"),
                run_id=task.run_id,
                task_id=task.id,
                agent_id=agent.spec.id,
                type="task.started",
                payload={"title": task.title},
            )
        )

        result = await agent.execute(task)
        for artifact in result.artifacts:
            if artifact.id not in task.artifacts:
                task.artifacts.append(artifact.id)
            self.store.save_artifact(artifact)
            self.store.save_task(task)
            artifacts.append(artifact)
            await self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=task.run_id,
                    task_id=task.id,
                    agent_id=agent.spec.id,
                    type="artifact.created",
                    payload={"artifact_id": artifact.id, "kind": artifact.kind, "summary": artifact.summary},
                )
            )

        if result.tool_requests:
            tool_outcome = await self.tool_gateway.process_requests(
                run_id=task.run_id,
                task=task,
                agent_id=agent.spec.id,
                tool_requests=result.tool_requests,
            )
            for artifact in tool_outcome.artifacts:
                if artifact.id not in task.artifacts:
                    task.artifacts.append(artifact.id)
                self.store.save_artifact(artifact)
                self.store.save_task(task)
                artifacts.append(artifact)
                await self.event_bus.publish(
                    Event(
                        id=new_id("evt"),
                        run_id=task.run_id,
                        task_id=task.id,
                        agent_id=agent.spec.id,
                        type="artifact.created",
                        payload={"artifact_id": artifact.id, "kind": artifact.kind, "summary": artifact.summary},
                    )
                )
            for event in tool_outcome.requested_events:
                await self.event_bus.publish(event)
            if tool_outcome.waiting_for_approval:
                self.task_board.update_status(task.id, TaskStatus.WAITING_FOR_APPROVAL)
                await self.event_bus.publish(
                    Event(
                        id=new_id("evt"),
                        run_id=task.run_id,
                        task_id=task.id,
                        agent_id=agent.spec.id,
                        type="task.waiting",
                        payload={"reason": "Waiting for tool approval", "notes": tool_outcome.notes},
                    )
                )
                return
            if tool_outcome.denied:
                self.task_board.update_status(task.id, TaskStatus.FAILED)
                await self.event_bus.publish(
                    Event(
                        id=new_id("evt"),
                        run_id=task.run_id,
                        task_id=task.id,
                        agent_id=agent.spec.id,
                        type="task.failed",
                        payload={"summary": "; ".join(tool_outcome.notes) or result.summary},
                    )
                )
                return

        for event in result.requested_events:
            await self.event_bus.publish(event)

        for child_task in result.child_tasks:
            await self.add_task(child_task)

        self.task_board.update_status(task.id, result.status)
        terminal_event = "task.completed" if result.status is TaskStatus.COMPLETED else "task.failed"
        await self.event_bus.publish(
            Event(
                id=new_id("evt"),
                run_id=task.run_id,
                task_id=task.id,
                agent_id=agent.spec.id,
                type=terminal_event,
                payload={"summary": result.summary},
            )
        )


def build_root_task(run_id: str, title: str, description: str, capability: str, priority: int = 100) -> Task:
    return Task(
        id=new_id("task"),
        run_id=run_id,
        title=title,
        description=description,
        required_capability=capability,
        priority=priority,
        status=TaskStatus.PENDING,
    )
