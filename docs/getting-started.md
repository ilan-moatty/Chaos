# Getting Started With Chaos

Chaos is a small control plane for multi-agent work. It is designed to make concurrent LLM tasks understandable by turning them into explicit runs, tasks, events, artifacts, and approvals.

## Core Concepts

### Run

A run is one top-level objective, like:

- "Design a runtime kernel"
- "Prepare a release brief"
- "Research orchestration patterns"

Runs are stored durably in SQLite and can be paused or resumed.

### Task

A task is a bounded unit of work owned by an agent capability such as:

- `research`
- `execution`
- `review`

Tasks can depend on other tasks, wait for approval, or spawn child tasks.

### Event

Every meaningful action becomes an event:

- task creation
- assignment
- tool request
- approval request
- completion

This is what makes the system debuggable.

### Artifact

Artifacts are the useful outputs of tasks and tools:

- research notes
- implementation outlines
- review reports
- tool execution results

### Approval

High-impact or side-effecting tools should not run immediately. Chaos records them as tool requests, pauses the task, and lets an operator approve or deny the action.

## Fastest Way To Try It

From the repo root:

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.webapp --db agent-control.db --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

This is the easiest way to experience Chaos because it exposes:

- run launch controls
- approval queue
- event timeline
- task board
- artifact viewer

If you want to run the dashboard in a more production-like mode, start it with an API token:

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.webapp \
  --db agent-control.db \
  --port 8000 \
  --environment production \
  --api-token "replace-me"
```

Then:

- open the dashboard as usual
- click `Set API Token` in the header
- paste the same token to unlock dashboard API access
- launch and resume actions will be accepted immediately, then continue in the background

Public operational endpoints:

- `GET /api/health`
- `GET /api/meta`
- `GET /api/jobs`
- `GET /api/jobs/<job_id>`

If you want the terminal-only version instead:

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.demo
```

This runs the built-in demo and prints the full timeline.

## Manual Operator Loop

### Step 1: Start a run

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db demo
```

This creates a run, starts tasks, and stops when a tool needs approval.

### Step 2: Check what is waiting

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db status
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db approvals
```

### Step 3: Approve or deny

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db approve <request_id>
```

Or:

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db deny <request_id> --reason "Not ready to publish."
```

### Step 4: Resume the run

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db resume <run_id>
```

## Custom Workflow Example

There is a realistic example module at:

- `src/agent_control/examples/release_brief.py`

Run it with:

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.examples.release_brief --db release-brief.db
```

That example creates a run to prepare a release brief. It uses:

- one research task
- one execution task
- one approval-gated publish request
- one review task after the publish step is approved

If the run pauses, use the CLI to inspect and resume it:

```bash
PYTHONPATH=src python3 -m agent_control.cli --db release-brief.db approvals
PYTHONPATH=src python3 -m agent_control.cli --db release-brief.db approve <request_id>
PYTHONPATH=src python3 -m agent_control.cli --db release-brief.db resume <run_id>
```

## How To Build Your Own Workflow

The simplest pattern is:

1. Build the runtime.
2. Submit a run.
3. Create root tasks.
4. Add task inputs that influence planning.
5. Call `run_until_stable()`.
6. If needed, approve pending tools and call `resume_run()`.

Minimal example:

```python
from agent_control.runtime import build_runtime
from agent_control.supervisor import build_root_task

supervisor, store, _ = build_runtime("my-run.db")
run = await supervisor.submit_run("Prepare a launch summary.")

task = build_root_task(
    run_id=run.id,
    title="Draft launch summary",
    description="Prepare a summary and request publication.",
    capability="execution",
    priority=10,
)
task.inputs["request_publish_approval"] = True
task.inputs["publish_channel"] = "operator"

await supervisor.add_task(task)
await supervisor.run_until_stable(run)
```

## Where To Customize

### Planning logic

Edit `src/agent_control/model_adapters.py`.

This is where agent capability maps to:

- produced artifacts
- proposed tool calls
- summary outputs

### Agent wiring

Edit `src/agent_control/runtime.py`.

This is where you register:

- agents
- capabilities
- tools
- store
- supervisor

### Tool behavior

Edit `src/agent_control/tool_gateway.py` and tool registrations in `src/agent_control/runtime.py`.

This is where you control:

- approval requirements
- timeouts
- idempotency
- execution handlers

### Persistence

Edit `src/agent_control/store.py`.

This is the durable source of truth for:

- runs
- tasks
- events
- artifacts
- tool requests

## Recommended Next Improvements

If you want to turn Chaos into a more complete product, the next highest-value steps are:

- replace the rule-based planner with a real model provider adapter
- move from SQLite-only local state to Postgres plus migrations
- split the web app from background workers and queues
- add real auth/RBAC instead of single shared API-token protection
- add retries and dead-letter handling for failed tools
