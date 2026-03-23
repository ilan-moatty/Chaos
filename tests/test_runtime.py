from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_control.models import RunStatus, ToolRequestStatus
from agent_control.runtime import approve_tool_request, build_runtime
from agent_control.supervisor import build_root_task


class RuntimeFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "state.db")

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_run_pauses_for_pending_approval(self) -> None:
        supervisor, store, _ = build_runtime(self.db_path)
        run = await supervisor.submit_run("Pause until approval.")

        task = build_root_task(
            run_id=run.id,
            title="Design runtime kernel",
            description="Define runtime pieces.",
            capability="execution",
            priority=1,
        )
        task.inputs["request_publish_approval"] = True

        await supervisor.add_task(task)
        await supervisor.run_until_stable(run)

        refreshed_run = store.get_run(run.id)
        pending = store.list_tool_requests(run_id=run.id, status=ToolRequestStatus.PENDING_APPROVAL)

        self.assertEqual(refreshed_run.status, RunStatus.PAUSED)
        self.assertEqual(len(pending), 1)
        self.assertEqual(store.get_task(task.id).status.value, "WAITING_FOR_APPROVAL")
        store.close()

    async def test_approved_run_resumes_and_completes(self) -> None:
        supervisor, store, _ = build_runtime(self.db_path)
        run = await supervisor.submit_run("Pause, approve, and complete.")

        task = build_root_task(
            run_id=run.id,
            title="Design runtime kernel",
            description="Define runtime pieces.",
            capability="execution",
            priority=1,
        )
        task.inputs["request_publish_approval"] = True
        task.inputs["spawn_review"] = True

        await supervisor.add_task(task)
        await supervisor.run_until_stable(run)

        pending = store.list_tool_requests(run_id=run.id, status=ToolRequestStatus.PENDING_APPROVAL)
        approve_tool_request(store, pending[0].id)

        resumed_run = await supervisor.resume_run(run.id)
        await supervisor.run_until_stable(resumed_run)

        refreshed_run = store.get_run(run.id)
        requests = store.list_tool_requests(run_id=run.id)
        events = [event.type for event in store.list_events(run.id)]

        self.assertEqual(refreshed_run.status, RunStatus.COMPLETED)
        self.assertIn(ToolRequestStatus.COMPLETED, [request.status for request in requests])
        self.assertIn("tool.completed", events)
        self.assertIn("run.completed", events)
        store.close()
