from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agent_control.models import ToolRequestStatus
from agent_control.runtime import build_runtime
from agent_control.workflows import start_release_brief_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a release brief workflow in Chaos.")
    parser.add_argument("--db", default="release-brief.db", help="Path to the SQLite state database.")
    return parser


async def main(db_path: str) -> None:
    supervisor, store, _ = build_runtime(db_path)
    run = await start_release_brief_run(supervisor)

    refreshed_run = store.get_run(run.id)
    print(f"run_id={refreshed_run.id} status={refreshed_run.status.value}")

    pending = store.list_tool_requests(run_id=run.id, status=ToolRequestStatus.PENDING_APPROVAL)
    if pending:
        print("pending approvals:")
        for request in pending:
            print(f"  request_id={request.id} tool={request.tool_name} args={request.arguments}")
        print("\nnext steps:")
        print(f"  PYTHONPATH=src python3 -m agent_control.cli --db {db_path} approvals")
        print(f"  PYTHONPATH=src python3 -m agent_control.cli --db {db_path} approve <request_id>")
        print(f"  PYTHONPATH=src python3 -m agent_control.cli --db {db_path} resume {run.id}")
    else:
        print("workflow completed without pending approvals.")

    store.close()


if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(main(str(Path(args.db))))
