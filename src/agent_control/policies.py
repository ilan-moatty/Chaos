from __future__ import annotations

from agent_control.models import Event, ToolSpec, new_id


class PolicyEngine:
    """Policy hook for approvals, budgets, and safety rules."""

    def tool_requires_approval(self, tool: ToolSpec) -> bool:
        return tool.requires_approval or tool.destructive

    def build_approval_event(self, run_id: str, task_id: str, agent_id: str, tool: ToolSpec) -> Event:
        return Event(
            id=new_id("evt"),
            run_id=run_id,
            type="approval.requested",
            task_id=task_id,
            agent_id=agent_id,
            payload={
                "tool_id": tool.id,
                "tool_name": tool.name,
                "reason": "Tool is classified as side-effecting or approval-gated.",
            },
        )
