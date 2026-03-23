from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List

from agent_control.event_bus import EventBus
from agent_control.models import (
    Artifact,
    Event,
    Task,
    ToolRequest,
    ToolRequestStatus,
    ToolSpec,
    new_id,
    stable_key,
)
from agent_control.store import SqliteStore

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class ToolHandlingResult:
    waiting_for_approval: bool = False
    denied: bool = False
    artifacts: List[Artifact] = field(default_factory=list)
    requested_events: List[Event] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


class ToolGateway:
    """Central entry point for tool policy, auditing, and execution."""

    def __init__(self, store: SqliteStore, event_bus: EventBus) -> None:
        self.store = store
        self.event_bus = event_bus
        self._tool_specs: Dict[str, ToolSpec] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register_tool(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._tool_specs[spec.name] = spec
        self._handlers[spec.name] = handler

    async def process_requests(
        self,
        *,
        run_id: str,
        task: Task,
        agent_id: str,
        tool_requests: List[ToolRequest],
    ) -> ToolHandlingResult:
        result = ToolHandlingResult()
        for request in tool_requests:
            outcome = await self._process_request(
                run_id=run_id,
                task=task,
                agent_id=agent_id,
                request=request,
            )
            result.waiting_for_approval = result.waiting_for_approval or outcome.waiting_for_approval
            result.denied = result.denied or outcome.denied
            result.artifacts.extend(outcome.artifacts)
            result.requested_events.extend(outcome.requested_events)
            result.notes.extend(outcome.notes)
        return result

    async def _process_request(
        self,
        *,
        run_id: str,
        task: Task,
        agent_id: str,
        request: ToolRequest,
    ) -> ToolHandlingResult:
        outcome = ToolHandlingResult()
        spec = self._tool_specs.get(request.tool_name)
        handler = self._handlers.get(request.tool_name)
        if spec is None or handler is None:
            outcome.denied = True
            outcome.notes.append(f"Tool {request.tool_name} is not registered.")
            return outcome

        existing = self.store.find_tool_request(task.id, request.idempotency_key)
        if existing is None:
            self.store.save_tool_request(request)
            await self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=run_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    type="tool.requested",
                    payload={
                        "tool_name": request.tool_name,
                        "arguments": request.arguments,
                        "requires_approval": request.requires_approval,
                    },
                )
            )
            existing = request

        if existing.status is ToolRequestStatus.DENIED:
            outcome.denied = True
            outcome.notes.append(f"Tool request {existing.id} was denied.")
            return outcome

        if existing.status is ToolRequestStatus.COMPLETED:
            outcome.notes.append(f"Tool request {existing.id} already completed.")
            return outcome

        if existing.status is ToolRequestStatus.PENDING_APPROVAL and request.requires_approval:
            if existing.id == request.id:
                await self.event_bus.publish(
                    Event(
                        id=new_id("evt"),
                        run_id=run_id,
                        task_id=task.id,
                        agent_id=agent_id,
                        type="approval.requested",
                        payload={
                            "tool_request_id": existing.id,
                            "tool_name": request.tool_name,
                            "arguments": request.arguments,
                        },
                    )
                )
            outcome.waiting_for_approval = True
            outcome.notes.append(f"Tool request {existing.id} is waiting for approval.")
            return outcome

        if existing.status is ToolRequestStatus.APPROVED or not request.requires_approval:
            self.store.update_tool_request(existing.id, ToolRequestStatus.RUNNING)
            await self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=run_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    type="tool.started",
                    payload={"tool_request_id": existing.id, "tool_name": request.tool_name},
                )
            )
            try:
                tool_result = await asyncio.wait_for(
                    handler(existing.arguments),
                    timeout=spec.timeout_seconds,
                )
            except Exception as exc:
                self.store.update_tool_request(
                    existing.id,
                    ToolRequestStatus.FAILED,
                    error=str(exc),
                )
                await self.event_bus.publish(
                    Event(
                        id=new_id("evt"),
                        run_id=run_id,
                        task_id=task.id,
                        agent_id=agent_id,
                        type="tool.failed",
                        payload={
                            "tool_request_id": existing.id,
                            "tool_name": request.tool_name,
                            "error": str(exc),
                        },
                    )
                )
                outcome.denied = True
                outcome.notes.append(f"Tool request {existing.id} failed: {exc}")
                return outcome

            completed = self.store.update_tool_request(
                existing.id,
                ToolRequestStatus.COMPLETED,
                result=tool_result,
            )
            await self.event_bus.publish(
                Event(
                    id=new_id("evt"),
                    run_id=run_id,
                    task_id=task.id,
                    agent_id=agent_id,
                    type="tool.completed",
                    payload={
                        "tool_request_id": completed.id,
                        "tool_name": request.tool_name,
                        "result": tool_result,
                    },
                )
            )
            artifact = Artifact(
                id=stable_key(
                    "art",
                    {
                        "task_id": task.id,
                        "tool_request_id": completed.id,
                        "kind": f"tool_result.{request.tool_name}",
                    },
                ),
                task_id=task.id,
                kind=f"tool_result.{request.tool_name}",
                summary=f"Tool result for {request.tool_name}",
                content=tool_result,
            )
            outcome.artifacts.append(artifact)
            return outcome

        return outcome


def build_tool_request(
    *,
    run_id: str,
    task_id: str,
    agent_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
    requires_approval: bool,
) -> ToolRequest:
    return ToolRequest(
        id=new_id("toolreq"),
        run_id=run_id,
        task_id=task_id,
        agent_id=agent_id,
        tool_name=tool_name,
        arguments=arguments,
        idempotency_key=stable_key(
            "toolkey",
            {"task_id": task_id, "tool_name": tool_name, "arguments": arguments},
        ),
        status=ToolRequestStatus.PENDING_APPROVAL if requires_approval else ToolRequestStatus.APPROVED,
        requires_approval=requires_approval,
    )
