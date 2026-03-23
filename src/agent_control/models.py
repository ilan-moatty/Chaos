from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stable_key(prefix: str, payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"{prefix}_{digest}"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RunStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ToolRequestStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    FAILED = "FAILED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Budget:
    max_steps: int = 5
    max_tool_calls: int = 3
    max_seconds: float = 30.0


@dataclass
class Artifact:
    id: str
    task_id: str
    kind: str
    summary: str
    content: Dict[str, Any]
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Event:
    id: str
    run_id: str
    type: str
    payload: Dict[str, Any]
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Run:
    id: str
    objective: str
    status: RunStatus = RunStatus.ACTIVE
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class Task:
    id: str
    run_id: str
    title: str
    description: str
    required_capability: str
    parent_task_id: Optional[str] = None
    owner_agent_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 100
    dependencies: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    inputs: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


@dataclass
class ToolSpec:
    id: str
    name: str
    description: str
    destructive: bool = False
    requires_approval: bool = False
    timeout_seconds: float = 10.0


@dataclass
class AgentSpec:
    id: str
    name: str
    capabilities: List[str]
    tools: List[str]
    max_concurrency: int = 1


@dataclass
class ToolRequest:
    id: str
    run_id: str
    task_id: str
    agent_id: str
    tool_name: str
    arguments: Dict[str, Any]
    idempotency_key: str
    status: ToolRequestStatus = ToolRequestStatus.PENDING_APPROVAL
    requires_approval: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class OperationJob:
    id: str
    kind: str
    status: JobStatus
    operator_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    run_id: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class TaskResult:
    status: TaskStatus
    summary: str
    artifacts: List[Artifact] = field(default_factory=list)
    child_tasks: List[Task] = field(default_factory=list)
    requested_events: List[Event] = field(default_factory=list)
    tool_requests: List[ToolRequest] = field(default_factory=list)
