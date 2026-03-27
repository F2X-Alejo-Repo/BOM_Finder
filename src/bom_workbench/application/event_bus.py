"""Lightweight async-friendly event bus."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

EventT = TypeVar("EventT")
EventHandler = Callable[[EventT], Awaitable[Any] | Any]


class EventBus(Generic[EventT]):
    """Minimal publish/subscribe bus that supports sync and async handlers."""

    def __init__(self) -> None:
        self._handlers: list[EventHandler[EventT]] = []

    def subscribe(self, handler: EventHandler[EventT]) -> EventHandler[EventT]:
        """Register a handler and return it for decorator-style use."""

        if handler not in self._handlers:
            self._handlers.append(handler)
        return handler

    def unsubscribe(self, handler: EventHandler[EventT]) -> bool:
        """Remove a handler if present."""

        try:
            self._handlers.remove(handler)
        except ValueError:
            return False
        return True

    async def publish(self, event: EventT) -> list[Any]:
        """Publish an event to all current subscribers."""

        results: list[Any] = []
        for handler in tuple(self._handlers):
            result = handler(event)
            if inspect.isawaitable(result):
                result = await result
            results.append(result)
        return results


@dataclass(slots=True, frozen=True)
class ImportStarted:
    """Event emitted when an import flow begins."""

    source_file: str
    project_name: str


@dataclass(slots=True, frozen=True)
class ImportPreviewReady:
    """Event emitted when a preview payload is ready."""

    source_file: str
    project_name: str
    row_count: int
    warning_count: int


@dataclass(slots=True, frozen=True)
class ImportCompleted:
    """Event emitted after rows have been persisted."""

    source_file: str
    project_name: str
    project_id: int
    imported_count: int


@dataclass(slots=True, frozen=True)
class ImportFailed:
    """Event emitted when an import flow fails."""

    source_file: str
    project_name: str
    error_message: str


@dataclass(slots=True, frozen=True)
class JobQueued:
    """Event emitted when a job enters the queue."""

    job_id: int
    job_type: str
    total_rows: int


@dataclass(slots=True, frozen=True)
class JobStarted:
    """Event emitted when a job starts running."""

    job_id: int
    job_type: str
    total_rows: int


@dataclass(slots=True, frozen=True)
class JobProgress:
    """Event emitted after a job row has been processed."""

    job_id: int
    job_type: str
    row_id: int
    completed_rows: int
    failed_rows: int


@dataclass(slots=True, frozen=True)
class JobCompleted:
    """Event emitted when a job completes successfully or with errors."""

    job_id: int
    job_type: str
    state: str
    completed_rows: int
    failed_rows: int


@dataclass(slots=True, frozen=True)
class JobFailed:
    """Event emitted when a job fails irrecoverably."""

    job_id: int
    job_type: str
    error_message: str


@dataclass(slots=True, frozen=True)
class JobCancelled:
    """Event emitted when a job is cancelled."""

    job_id: int
    job_type: str
    completed_rows: int
    failed_rows: int


@dataclass(slots=True, frozen=True)
class JobPaused:
    """Event emitted when a job is paused."""

    job_id: int
    job_type: str


@dataclass(slots=True, frozen=True)
class JobResumed:
    """Event emitted when a job is resumed."""

    job_id: int
    job_type: str
