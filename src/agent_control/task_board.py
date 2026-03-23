from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from agent_control.models import Task, TaskStatus
from agent_control.store import SqliteStore


class TaskBoard:
    """Central source of truth for task lifecycle and ownership."""

    def __init__(self, store: Optional[SqliteStore] = None) -> None:
        self._tasks: Dict[str, Task] = {}
        self._store = store

    def add(self, task: Task) -> None:
        self._tasks[task.id] = task
        if self._store is not None:
            self._store.save_task(task)

    def get(self, task_id: str) -> Task:
        return self._tasks[task_id]

    def list(self) -> List[Task]:
        return list(self._tasks.values())

    def load_tasks(self, tasks: Iterable[Task]) -> None:
        self._tasks = {task.id: task for task in tasks}

    def update_status(self, task_id: str, status: TaskStatus) -> Task:
        task = self.get(task_id)
        task.status = status
        if self._store is not None:
            self._store.save_task(task)
        return task

    def assign(self, task_id: str, agent_id: str) -> Task:
        task = self.get(task_id)
        task.owner_agent_id = agent_id
        if self._store is not None:
            self._store.save_task(task)
        return task

    def ready_tasks(self, run_id: Optional[str] = None) -> Iterable[Task]:
        for task in self._tasks.values():
            if run_id is not None and task.run_id != run_id:
                continue
            if task.status is TaskStatus.READY and self.dependencies_completed(task):
                yield task

    def dependencies_completed(self, task: Task) -> bool:
        return all(self.get(dep_id).status is TaskStatus.COMPLETED for dep_id in task.dependencies)

    def children_of(self, parent_task_id: str) -> List[Task]:
        return [task for task in self._tasks.values() if task.parent_task_id == parent_task_id]

    def root_tasks(self) -> List[Task]:
        return [task for task in self._tasks.values() if task.parent_task_id is None]

    def tasks_for_run(self, run_id: str) -> List[Task]:
        return [task for task in self._tasks.values() if task.run_id == run_id]

    def all_completed(self, run_id: Optional[str] = None) -> bool:
        tasks = self.list()
        if run_id is not None:
            tasks = [task for task in tasks if task.run_id == run_id]
        return bool(tasks) and all(task.status is TaskStatus.COMPLETED for task in tasks)
