# Multi-Agent Control Plane Design

## Problem

When multiple LLMs and tool-enabled agents run at once, the system gets confusing fast:

- conversations become the state store
- agent responsibilities blur
- tools are called without enough visibility
- multiple subtasks compete for the same context
- humans lose the ability to approve, redirect, or understand what happened

The fix is not "more agents." The fix is a control plane.

## Recommendation

Build a system with one explicit orchestrator and many bounded workers:

1. `Supervisor`
   Owns task decomposition, routing, retries, escalation, and final synthesis.
2. `Task Board`
   Durable source of truth for work items, dependencies, ownership, and status.
3. `Event Log`
   Append-only stream for every decision, tool call, handoff, observation, and result.
4. `Tool Gateway`
   Normalizes tool execution, permissions, timeouts, idempotency, and auditing.
5. `Human Inbox`
   Interrupts the flow for approvals, edits, or rerouting without losing state.
6. `Specialized Agents`
   Each agent gets a narrow role, limited tools, and a small task-scoped context.

This gives you multitasking without losing control.

## Design Principles

### 1. Tasks are the unit of work

Do not let raw chat threads become the only coordination mechanism.

Each task should have:

- `task_id`
- `goal`
- `inputs`
- `constraints`
- `owner`
- `dependencies`
- `status`
- `artifacts`
- `budget`
- `priority`

Agents can still chat, but that chat should be attached to a task.

### 2. Handoffs must be structured contracts

An agent should never say only "ask the other agent."

A valid handoff should include:

- target capability or agent
- requested outcome
- required inputs
- definition of done
- tool budget
- whether human approval is required

### 3. Tools need a gateway, not direct chaos

Different tools should be wrapped behind a common execution envelope:

- schema-validated input
- timeout
- retries
- side-effect classification
- audit logging
- optional approval requirement

This is how you keep ten tools from behaving like ten different systems.

### 4. Parallelism should happen at the task graph level

Do not ask one agent to "think about five things in parallel" inside one unstructured prompt.

Instead:

- decompose into child tasks
- execute independent tasks concurrently
- merge results in a review or synthesis step

This is easier to monitor and much easier to debug.

### 5. Human control must be a first-class state transition

Human review should not be an out-of-band Slack message.

Model it as:

- `WAITING_FOR_APPROVAL`
- `WAITING_FOR_INPUT`
- `PAUSED`
- `RESUMED`

This makes the system resumable and observable.

### 6. Memory must be layered

Use three layers:

- `Task memory`: notes and artifacts specific to one task
- `Run memory`: shared facts for the current end-to-end request
- `Long-term memory`: reusable preferences, learned procedures, or environment knowledge

Do not give every agent the full long-term memory on every step.

## Execution Model

### Control loop

1. Intake a user request as a root task.
2. Supervisor decides whether the task is:
   - direct-answer
   - decomposable
   - tool-first
   - requires-human-approval
3. Child tasks are spawned with explicit contracts.
4. Scheduler dispatches ready tasks to eligible agents.
5. Agents produce:
   - observations
   - tool requests
   - proposed child tasks
   - artifacts
   - completion summaries
6. Policy engine approves, rejects, or pauses risky actions.
7. Review agent or supervisor merges outputs.
8. Final response is synthesized from artifacts, not only from agent chatter.

### State machine

Suggested task states:

- `PENDING`
- `READY`
- `RUNNING`
- `BLOCKED`
- `WAITING_FOR_APPROVAL`
- `WAITING_FOR_INPUT`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

### Event types

Suggested events:

- `task.created`
- `task.ready`
- `task.started`
- `task.blocked`
- `task.completed`
- `task.failed`
- `agent.assigned`
- `agent.handoff_requested`
- `tool.requested`
- `tool.started`
- `tool.completed`
- `tool.failed`
- `approval.requested`
- `approval.granted`
- `approval.denied`
- `artifact.created`
- `run.summary_updated`

## Recommended Agent Topology

Start with four roles only:

1. `Supervisor`
   Decides routing and manages the full task graph.
2. `Research Agent`
   Reads docs, gathers facts, and returns structured evidence.
3. `Execution Agent`
   Writes code, performs changes, or invokes operational tools.
4. `Review Agent`
   Checks quality, consistency, missing tests, and merge readiness.

This is enough for most systems. Add more agents only after you see a real bottleneck.

## Suggested UI Model

If you build an interface later, center it around:

- a task board
- a live event timeline
- a per-agent inbox/outbox
- a tool approvals queue
- a merged artifact viewer

The main operator view should answer:

- What is running now?
- What is blocked?
- Which agent owns what?
- Which tool calls are waiting?
- What changed in the last minute?

## Suggested Data Model

```text
Run
  id
  objective
  status
  created_at

Task
  id
  run_id
  parent_task_id
  title
  description
  owner_agent_id
  required_capability
  status
  priority
  dependencies[]
  artifacts[]
  budget

Artifact
  id
  task_id
  kind
  content_ref
  summary

Event
  id
  run_id
  task_id
  agent_id
  type
  payload
  created_at
```

## Implementation Advice

### Phase 1

Build the runtime kernel only:

- task state machine
- event log
- scheduler
- tool gateway
- supervisor

No fancy autonomy yet.

### Phase 2

Add:

- pause and resume
- approval policies
- concurrency limits
- retries and dead-letter handling
- artifact merge rules

### Phase 3

Add:

- UI
- long-term memory
- model routing by budget and quality tier
- analytics on tool success, latency, and agent usefulness

## Concrete Recommendation

If you want a practical starting point, I would build this as:

- backend runtime in Python with `asyncio`
- event-driven orchestration
- explicit task graph
- MCP or similar standardized tool wrappers at the gateway layer
- one supervisor model plus a few specialist workers
- mandatory human approval on high-impact tools

I would not start with a pure free-form group chat of agents. That pattern feels impressive early and becomes unmanageable once the system does real work.

## What existing systems get right

These external systems influenced the design:

- OpenAI Agents and Agent Builder emphasize workflows made of agents, tools, and control flow.
- LangGraph emphasizes explicit graph state, persistence, and interrupts for human-in-the-loop.
- AutoGen shows a strong message-driven handoff model between agents.
- CrewAI separates high-level agent collaboration from lower-level event-driven flows.

The best production design is usually a hybrid:

- LangGraph-style explicit state
- AutoGen-style event messaging
- OpenAI-style handoffs and tool abstractions
- Temporal-style durability if runs become long-lived

## Reference Inspirations

- OpenAI Agents SDK overview:
  [https://openai.github.io/openai-agents-js/](https://openai.github.io/openai-agents-js/)
- OpenAI Agents SDK handoffs:
  [https://openai.github.io/openai-agents-python/handoffs/](https://openai.github.io/openai-agents-python/handoffs/)
- OpenAI Agent Builder:
  [https://platform.openai.com/docs/guides/agent-builder](https://platform.openai.com/docs/guides/agent-builder)
- LangChain multi-agent patterns:
  [https://docs.langchain.com/oss/python/langchain/multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent)
- LangGraph interrupts and human-in-the-loop:
  [https://docs.langchain.com/oss/python/langgraph/interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Microsoft AutoGen handoffs:
  [https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/design-patterns/handoffs.html](https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/design-patterns/handoffs.html)
- CrewAI introduction and flows:
  [https://docs.crewai.com/en/introduction](https://docs.crewai.com/en/introduction)
  [https://www.crewai.com/crewai-flows](https://www.crewai.com/crewai-flows)
- Model Context Protocol introduction:
  [https://modelcontextprotocol.io/](https://modelcontextprotocol.io/)
- Temporal durable execution overview:
  [https://temporal.io/](https://temporal.io/)

## Decision Summary

If your goal is to handle many agents and tools without confusion, the best design is:

- one orchestrator
- explicit task graph
- append-only event log
- tool gateway
- human inbox
- narrow specialist agents

That gives you control, traceability, and real multitasking.
