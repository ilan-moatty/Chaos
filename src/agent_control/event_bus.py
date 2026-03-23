from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator, DefaultDict, List, Optional

from agent_control.models import Event
from agent_control.store import SqliteStore


class EventBus:
    """Append-only event stream with lightweight subscriptions."""

    def __init__(self, store: Optional[SqliteStore] = None) -> None:
        self._events: List[Event] = []
        self._subscribers: DefaultDict[str, List[asyncio.Queue[Event]]] = defaultdict(list)
        self._store = store

    @property
    def events(self) -> List[Event]:
        return list(self._events)

    async def publish(self, event: Event) -> None:
        self._events.append(event)
        if self._store is not None:
            self._store.save_event(event)
        for queue in self._subscribers[event.type]:
            await queue.put(event)
        for queue in self._subscribers["*"]:
            await queue.put(event)

    async def subscribe(self, event_type: str = "*") -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers[event_type].append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers[event_type].remove(queue)
