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

## Run the demo

```bash
PYTHONPATH=src python3 -m agent_control.demo
```

The demo simulates a supervisor assigning a root task plus concurrent subtasks to specialized agents and emits a timeline of structured events.

## Operator CLI

```bash
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db demo
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db approvals
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db approve <request_id>
PYTHONPATH=src python3 -m agent_control.cli --db agent-control.db resume <run_id>
```

This gives you a simple human-in-the-loop control surface before building a richer UI.
