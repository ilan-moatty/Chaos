from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from agent_control.config import ChaosSettings
from agent_control.webapp import ChaosWebApp


class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "ui.db")
        self.app = ChaosWebApp(self.db_path)

    def tearDown(self) -> None:
        self.app.close()
        self.temp_dir.cleanup()

    def get_json(self, path: str, headers=None):
        status, _, body = self.app.dispatch("GET", path, headers=headers)
        self.assertEqual(status.value, 200)
        return __import__("json").loads(body.decode("utf-8"))

    def post_json(self, path: str, payload=None, headers=None):
        status, _, body = self.app.dispatch("POST", path, body=payload, headers=headers)
        self.assertIn(status.value, {200, 201, 202})
        return __import__("json").loads(body.decode("utf-8"))

    def wait_for(self, predicate, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        self.fail("Timed out waiting for condition.")

    def test_dashboard_and_run_flow(self) -> None:
        dashboard = self.get_json("/api/dashboard")
        self.assertEqual(dashboard["stats"]["run_count"], 0)

        detail = self.post_json("/api/runs/demo")
        run_id = detail["run"]["id"]
        detail = self.wait_for(
            lambda: (
                refreshed
                if (refreshed := self.get_json(f"/api/runs/{run_id}"))["run"]["status"] == "PAUSED"
                else None
            )
        )

        approvals = [item for item in detail["tool_requests"] if item["status"] == "PENDING_APPROVAL"]
        self.assertEqual(len(approvals), 1)

        request_id = approvals[0]["id"]
        self.post_json(f"/api/tool-requests/{request_id}/approve")
        self.post_json(f"/api/runs/{run_id}/resume")
        refreshed = self.wait_for(
            lambda: (
                next_detail
                if (next_detail := self.get_json(f"/api/runs/{run_id}"))["run"]["status"] == "COMPLETED"
                else None
            )
        )
        self.assertEqual(refreshed["run"]["status"], "COMPLETED")

    def test_index_serves_ui(self) -> None:
        status, _, html = self.app.dispatch("GET", "/")
        self.assertEqual(status.value, 200)
        self.assertIn(b"Chaos Control Room", html)

    def test_meta_and_health_are_public(self) -> None:
        meta = self.get_json("/api/meta")
        health = self.get_json("/api/health")

        self.assertEqual(meta["product"], "Chaos")
        self.assertIn("auth", meta)
        self.assertTrue(health["ok"])
        self.assertIn("background_jobs", health)

    def test_jobs_endpoint_reports_background_launch(self) -> None:
        detail = self.post_json("/api/runs/demo")
        job_id = detail["job"]["id"]

        jobs = self.get_json("/api/jobs")
        self.assertTrue(any(job["id"] == job_id for job in jobs["jobs"]))

        job = self.wait_for(
            lambda: (
                job_detail["job"]
                if (job_detail := self.get_json(f"/api/jobs/{job_id}"))["job"]["status"] in {"RUNNING", "COMPLETED"}
                else None
            )
        )
        self.assertIn(job["status"], {"RUNNING", "COMPLETED"})

    def test_api_token_protects_control_endpoints_and_records_operator_actions(self) -> None:
        protected_app = ChaosWebApp(
            self.db_path,
            settings=ChaosSettings(db_path=self.db_path, api_token="secret-token"),
        )

        status, _, body = protected_app.dispatch("GET", "/api/dashboard")
        self.assertEqual(status.value, 401)
        self.assertIn("Unauthorized", body.decode("utf-8"))

        headers = {
            "Authorization": "Bearer secret-token",
            "X-Chaos-Operator": "ops-user",
        }
        status, _, body = protected_app.dispatch("POST", "/api/runs/demo", headers=headers)
        self.assertEqual(status.value, 202)
        detail = __import__("json").loads(body.decode("utf-8"))
        detail = self.wait_for(
            lambda: (
                refreshed
                if (refreshed := protected_app.run_detail(detail["run"]["id"]))["run"]["status"] == "PAUSED"
                else None
            )
        )

        approvals = [item for item in detail["tool_requests"] if item["status"] == "PENDING_APPROVAL"]
        request_id = approvals[0]["id"]
        status, _, body = protected_app.dispatch(
            "POST", f"/api/tool-requests/{request_id}/approve", headers=headers
        )
        self.assertEqual(status.value, 200)

        events = protected_app.run_detail(detail["run"]["id"])["events"]
        operator_events = [event for event in events if event["type"] == "operator.action"]

        self.assertTrue(operator_events)
        self.assertEqual(operator_events[0]["payload"]["operator_id"], "ops-user")
        protected_app.close()
