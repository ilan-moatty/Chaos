from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List

from agent_control.models import Event, Task


@dataclass
class PlannedArtifact:
    kind: str
    summary: str
    content: Dict[str, Any]


@dataclass
class PlannedToolCall:
    tool_name: str
    arguments: Dict[str, Any]


@dataclass
class ModelDecision:
    summary: str
    artifacts: List[PlannedArtifact] = field(default_factory=list)
    tool_calls: List[PlannedToolCall] = field(default_factory=list)
    requested_events: List[Event] = field(default_factory=list)


class ModelAdapter(ABC):
    """Abstract planner that turns a task into structured agent work."""

    @abstractmethod
    async def plan(self, capability: str, task: Task, allowed_tools: List[str]) -> ModelDecision:
        raise NotImplementedError


class RuleBasedModelAdapter(ModelAdapter):
    """Deterministic adapter that keeps the runtime testable and provider-agnostic."""

    async def plan(self, capability: str, task: Task, allowed_tools: List[str]) -> ModelDecision:
        if capability == "research":
            return ModelDecision(
                summary=f"Completed research for {task.title}",
                artifacts=[
                    PlannedArtifact(
                        kind="research_summary",
                        summary=f"Research notes for {task.title}",
                        content={
                            "findings": [
                                "Use explicit task state instead of raw chat as the system of record.",
                                "Keep tool execution behind a gateway with policy checks.",
                                "Parallelize with child tasks, then merge via review.",
                            ]
                        },
                    )
                ],
            )

        if capability == "execution":
            tool_calls: List[PlannedToolCall] = []
            if task.inputs.get("request_publish_approval") and "publish_report" in allowed_tools:
                tool_calls.append(
                    PlannedToolCall(
                        tool_name="publish_report",
                        arguments={
                            "channel": task.inputs.get("publish_channel", "operator"),
                            "message": f"Share implementation plan for '{task.title}'",
                        },
                    )
                )
            return ModelDecision(
                summary=f"Prepared implementation plan for {task.title}",
                artifacts=[
                    PlannedArtifact(
                        kind="implementation_note",
                        summary=f"Implementation outline for {task.title}",
                        content={
                            "components": [
                                "supervisor",
                                "task_board",
                                "event_bus",
                                "policy_engine",
                                "tool_gateway",
                                "operator_inbox",
                            ]
                        },
                    )
                ],
                tool_calls=tool_calls,
            )

        if capability == "review":
            return ModelDecision(
                summary=f"Reviewed {task.title}",
                artifacts=[
                    PlannedArtifact(
                        kind="review_report",
                        summary=f"Review for {task.title}",
                        content={
                            "checks": [
                                "Each agent should have restricted tools.",
                                "High-impact tools should require approval.",
                                "Runs should be reconstructable from events.",
                            ]
                        },
                    )
                ],
            )

        return ModelDecision(summary=f"No-op decision for {task.title}")
