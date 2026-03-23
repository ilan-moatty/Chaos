# Chaos

This workspace contains a greenfield proposal and starter implementation for handling multiple agents, models, and tools without turning the system into an untraceable group chat.

The core idea is simple:

- treat work as `tasks`, not just messages
- separate the `control plane` from the agents that do work
- keep every handoff, tool call, approval, and result as structured events
- allow concurrency, but only through explicit task state and scheduling rules

The recommended architecture is documented in [docs/multi-agent-control-plane.md](/Users/ilan/code/chaos/docs/multi-agent-control-plane.md).

The starter Python package shows the minimal runtime shape:

- `EventBus`: append-only event stream with subscribers
- `TaskBoard`: task state, ownership, and lifecycle
- `Supervisor`: assigns work, tracks dependencies, and enforces policies
- `Agent`: workers that act on task contracts rather than arbitrary chat history
- `PolicyEngine`: place for approvals, budgets, and tool restrictions
- `SqliteStore`: durable state for runs, tasks, events, artifacts, and approvals
- `ToolGateway`: central tool auditing, approval, and execution path

## Why this shape

Most failed multi-agent systems make one of these mistakes:

- too much hidden state in prompts
- too many tools exposed to every agent
- no durable task model
- no clean pause/resume path for humans
- parallelism without coordination

This scaffold is designed to avoid those failure modes first.

## Quick Start

### 1. Launch the operator UI

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.webapp --db agent-control.db --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The UI gives you:

- a modern run dashboard
- launch buttons for sample workflows
- task board and event timeline
- approval and resume controls
- artifact summaries for each run
- background execution for run launch and resume operations

For a more production-like local setup, you can protect the control API with a token:

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.webapp \
  --db agent-control.db \
  --port 8000 \
  --environment production \
  --api-token "replace-me"
```

When token protection is enabled:

- `/api/health` and `/api/meta` stay public for health checks and bootstrapping
- the dashboard will prompt you for an API token in the browser
- mutating operator actions are recorded as `operator.action` events
- run launch and resume requests are queued as background jobs instead of blocking the HTTP request

You can also configure the same settings with environment variables:

- `CHAOS_API_TOKEN`
- `CHAOS_ENV`
- `CHAOS_OPERATOR_HEADER`
- `CHAOS_REQUEST_LOGGING=1`

### 2. Run the demo in the terminal

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.demo
```

The demo simulates a supervisor assigning a root task plus concurrent subtasks to specialized agents and emits a timeline of structured events.

### 3. Operate it manually from the CLI

Create a run that pauses when approval is needed:

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db demo
```

Inspect the run and pending approvals:

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db approvals
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db status
```

Approve the pending tool request and resume the run:

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db approve <request_id>
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db resume <run_id>
```

This gives you a simple human-in-the-loop control surface before building a richer UI.

### 4. Run a custom workflow example

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m agent_control.examples.release_brief --db release-brief.db
```

This example creates a more realistic run for preparing a release brief with:

- research task
- execution task
- approval-gated publish step
- review task after approval

## Learn The Flow

The best place to start is the guide in [docs/getting-started.md](/Users/ilan/code/chaos/docs/getting-started.md).

It walks through:

- how runs, tasks, events, artifacts, and tool approvals fit together
- the manual operator loop
- how to write your own workflow script
- which files to edit when you want custom agents, tools, or planning logic

## Main Extension Points

- `build_runtime()` in `src/agent_control/runtime.py` wires agents, tools, store, and supervisor.
- `build_root_task()` in `src/agent_control/supervisor.py` is the simplest way to create new tasks.
- `RuleBasedModelAdapter` in `src/agent_control/model_adapters.py` is where planning logic lives today.
- `ToolGateway` in `src/agent_control/tool_gateway.py` is the right place for approval, retries, and tool auditing.
- `SqliteStore` in `src/agent_control/store.py` is the durable system of record.

## Production Foundations Added

Chaos now includes a first production-oriented slice in the web control plane:

- optional bearer-token protection for control APIs
- operator attribution via request headers
- public metadata and health endpoints
- request logging for HTTP traffic
- audit events for approval, deny, resume, and run launch actions
- in-process background jobs so long-running orchestration no longer runs on the request thread

The bigger production gaps still remain: real auth/RBAC, Postgres, worker queues, retries, and provider-backed agents.

## Run Tests

```bash
cd /Users/ilan/code/chaos
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
