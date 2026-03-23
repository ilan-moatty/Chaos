from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List

from agent_control.model_adapters import ModelAdapter, RuleBasedModelAdapter
from agent_control.models import AgentSpec, Artifact, Event, Task, TaskResult, TaskStatus, new_id, stable_key
from agent_control.tool_gateway import build_tool_request


class Agent(ABC):
    def __init__(self, spec: AgentSpec, model: ModelAdapter | None = None) -> None:
        self.spec = spec
        self.model = model or RuleBasedModelAdapter()
        self._active_tasks = 0

    @property
    def available(self) -> bool:
        return self._active_tasks < self.spec.max_concurrency

    async def execute(self, task: Task) -> TaskResult:
        self._active_tasks += 1
        try:
            return await self._execute(task)
        finally:
            self._active_tasks -= 1

    @abstractmethod
    async def _execute(self, task: Task) -> TaskResult:
        raise NotImplementedError


class ResearchAgent(Agent):
    async def _execute(self, task: Task) -> TaskResult:
        await asyncio.sleep(0.05)
        decision = await self.model.plan("research", task, self.spec.tools)
        artifact = Artifact(
            id=stable_key(
                "art",
                {"task_id": task.id, "kind": decision.artifacts[0].kind, "summary": decision.artifacts[0].summary},
            ),
            task_id=task.id,
            kind=decision.artifacts[0].kind,
            summary=decision.artifacts[0].summary,
            content=decision.artifacts[0].content,
        )
        return TaskResult(
            status=TaskStatus.COMPLETED,
            summary=decision.summary,
            artifacts=[artifact],
            requested_events=decision.requested_events,
        )


class ExecutionAgent(Agent):
    async def _execute(self, task: Task) -> TaskResult:
        await asyncio.sleep(0.05)
        decision = await self.model.plan("execution", task, self.spec.tools)
        artifact = Artifact(
            id=stable_key(
                "art",
                {"task_id": task.id, "kind": decision.artifacts[0].kind, "summary": decision.artifacts[0].summary},
            ),
            task_id=task.id,
            kind=decision.artifacts[0].kind,
            summary=decision.artifacts[0].summary,
            content=decision.artifacts[0].content,
        )
        child_tasks: List[Task] = []
        if task.inputs.get("spawn_review"):
            child_tasks.append(
                Task(
                    id=new_id("task"),
                    run_id=task.run_id,
                    parent_task_id=task.id,
                    title=f"Review {task.title}",
                    description="Validate the implementation outline and identify missing controls.",
                    required_capability="review",
                    priority=task.priority + 1,
                    status=TaskStatus.READY,
                )
            )
        tool_requests = [
            build_tool_request(
                run_id=task.run_id,
                task_id=task.id,
                agent_id=self.spec.id,
                tool_name=tool_call.tool_name,
                arguments=tool_call.arguments,
                requires_approval=True,
            )
            for tool_call in decision.tool_calls
        ]
        return TaskResult(
            status=TaskStatus.COMPLETED,
            summary=decision.summary,
            artifacts=[artifact],
            child_tasks=child_tasks,
            tool_requests=tool_requests,
            requested_events=decision.requested_events,
        )


class ReviewAgent(Agent):
    async def _execute(self, task: Task) -> TaskResult:
        await asyncio.sleep(0.05)
        decision = await self.model.plan("review", task, self.spec.tools)
        artifact = Artifact(
            id=stable_key(
                "art",
                {"task_id": task.id, "kind": decision.artifacts[0].kind, "summary": decision.artifacts[0].summary},
            ),
            task_id=task.id,
            kind=decision.artifacts[0].kind,
            summary=decision.artifacts[0].summary,
            content=decision.artifacts[0].content,
        )
        requested_event = Event(
            id=new_id("evt"),
            run_id=task.run_id,
            task_id=task.id,
            agent_id=self.spec.id,
            type="run.summary_updated",
            payload={"note": "Review completed with no blocking concerns in the starter outline."},
        )
        return TaskResult(
            status=TaskStatus.COMPLETED,
            summary=decision.summary,
            artifacts=[artifact],
            requested_events=decision.requested_events + [requested_event],
        )


class AgentRegistry:
    def __init__(self, agents: List[Agent]) -> None:
        self._agents: Dict[str, Agent] = {agent.spec.id: agent for agent in agents}

    def agents_for_capability(self, capability: str) -> List[Agent]:
        return [
            agent
            for agent in self._agents.values()
            if capability in agent.spec.capabilities and agent.available
        ]

    def get(self, agent_id: str) -> Agent:
        return self._agents[agent_id]
