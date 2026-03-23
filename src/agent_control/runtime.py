from __future__ import annotations

from typing import Tuple

from agent_control.agents import AgentRegistry, ExecutionAgent, ResearchAgent, ReviewAgent
from agent_control.event_bus import EventBus
from agent_control.models import AgentSpec, ToolRequestStatus, ToolSpec
from agent_control.store import SqliteStore
from agent_control.supervisor import Supervisor
from agent_control.task_board import TaskBoard
from agent_control.tool_gateway import ToolGateway


async def publish_report_tool(arguments: dict) -> dict:
    return {
        "channel": arguments["channel"],
        "message": arguments["message"],
        "published": True,
    }


def build_runtime(db_path: str) -> Tuple[Supervisor, SqliteStore, EventBus]:
    store = SqliteStore(db_path)
    event_bus = EventBus(store=store)
    task_board = TaskBoard(store=store)
    tool_gateway = ToolGateway(store=store, event_bus=event_bus)
    tool_gateway.register_tool(
        ToolSpec(
            id="tool_publish_report",
            name="publish_report",
            description="Publish a result summary to an operator-facing channel.",
            requires_approval=True,
            timeout_seconds=5.0,
        ),
        publish_report_tool,
    )
    agents = AgentRegistry(
        [
            ResearchAgent(
                AgentSpec(
                    id="agent_research",
                    name="Research Agent",
                    capabilities=["research"],
                    tools=["web_search", "docs_lookup"],
                    max_concurrency=2,
                )
            ),
            ExecutionAgent(
                AgentSpec(
                    id="agent_execution",
                    name="Execution Agent",
                    capabilities=["execution"],
                    tools=["editor", "shell", "publish_report"],
                    max_concurrency=2,
                )
            ),
            ReviewAgent(
                AgentSpec(
                    id="agent_review",
                    name="Review Agent",
                    capabilities=["review"],
                    tools=["review"],
                    max_concurrency=1,
                )
            ),
        ]
    )
    supervisor = Supervisor(
        event_bus=event_bus,
        task_board=task_board,
        agents=agents,
        store=store,
        tool_gateway=tool_gateway,
    )
    return supervisor, store, event_bus


def approve_tool_request(store: SqliteStore, request_id: str) -> None:
    store.update_tool_request(request_id, ToolRequestStatus.APPROVED)


def deny_tool_request(store: SqliteStore, request_id: str, reason: str) -> None:
    store.update_tool_request(request_id, ToolRequestStatus.DENIED, error=reason)
