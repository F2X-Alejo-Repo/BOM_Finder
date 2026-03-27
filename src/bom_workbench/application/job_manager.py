"""Async job manager with queued execution and bounded concurrency."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bom_workbench.domain.entities import Job
from bom_workbench.domain.enums import JobState
from bom_workbench.domain.ports import IJobRepository

from .event_bus import (
    EventBus,
    JobCancelled,
    JobCompleted,
    JobFailed,
    JobPaused,
    JobProgress,
    JobQueued,
    JobResumed,
    JobStarted,
)

RowExecutor = Callable[[int], Awaitable[bool | None]]


@dataclass(slots=True, frozen=True)
class JobSubmission:
    """Payload stored in the internal queue."""

    job_id: int
    executor: RowExecutor


class JobManager:
    """Coordinates tracked jobs with deterministic queue-based execution."""

    def __init__(
        self,
        repository: IJobRepository,
        *,
        event_bus: EventBus[Any] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._repository = repository
        self._event_bus = event_bus
        self._queue: asyncio.Queue[JobSubmission] = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._runner_task: asyncio.Task[None] | None = None
        self._closing = False
        self._paused_jobs: set[int] = set()
        self._cancelled_jobs: set[int] = set()
        self._pause_condition = asyncio.Condition()

    async def submit(self, job: Job, executor: RowExecutor) -> Job:
        """Persist a job as queued and schedule it for execution."""

        persisted = await self._repository.save(
            job.model_copy(update={"state": JobState.QUEUED.value})
        )
        if persisted.id is None:
            raise RuntimeError("Saved job did not return an id.")

        await self._publish(JobQueued(persisted.id, persisted.job_type, persisted.total_rows))
        await self._queue.put(JobSubmission(persisted.id, executor))
        self._ensure_runner()
        return persisted

    async def pause(self, job_id: int) -> Job:
        job = await self._require_job(job_id)
        if job.state in {JobState.COMPLETED, JobState.COMPLETED_WITH_ERRORS, JobState.FAILED, JobState.CANCELLED}:
            return job
        self._paused_jobs.add(job_id)
        updated = await self._repository.save(job.model_copy(update={"state": JobState.PAUSED.value}))
        await self._publish(JobPaused(job_id, updated.job_type))
        return updated

    async def resume(self, job_id: int) -> Job:
        job = await self._require_job(job_id)
        self._paused_jobs.discard(job_id)
        async with self._pause_condition:
            self._pause_condition.notify_all()
        if job.state == JobState.PAUSED:
            updated = await self._repository.save(job.model_copy(update={"state": JobState.QUEUED.value}))
        else:
            updated = job
        await self._publish(JobResumed(job_id, updated.job_type))
        return updated

    async def cancel(self, job_id: int) -> Job:
        job = await self._require_job(job_id)
        self._cancelled_jobs.add(job_id)
        self._paused_jobs.discard(job_id)
        async with self._pause_condition:
            self._pause_condition.notify_all()
        updated = await self._repository.save(job.model_copy(update={"state": JobState.CANCELLED.value}))
        await self._publish(JobCancelled(job_id, updated.job_type, updated.completed_rows, updated.failed_rows))
        return updated

    async def close(self) -> None:
        self._closing = True
        if self._runner_task is not None:
            self._runner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner_task

    def _ensure_runner(self) -> None:
        if self._runner_task is None or self._runner_task.done():
            self._runner_task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._closing:
            submission = await self._queue.get()
            async with self._semaphore:
                await self._execute(submission)

    async def _execute(self, submission: JobSubmission) -> None:
        job = await self._require_job(submission.job_id)
        if job.state == JobState.CANCELLED or submission.job_id in self._cancelled_jobs:
            return

        started = await self._repository.save(
            job.model_copy(update={"state": JobState.RUNNING.value, "started_at": _utc_now()})
        )
        await self._publish(JobStarted(started.id or submission.job_id, started.job_type, started.total_rows))

        completed_rows = started.completed_rows
        failed_rows = started.failed_rows

        try:
            for row_id in _parse_target_row_ids(started.target_row_ids):
                await self._wait_if_paused(started.id or submission.job_id)
                if started.id in self._cancelled_jobs or submission.job_id in self._cancelled_jobs:
                    await self._finalize_cancel(started, completed_rows, failed_rows)
                    return

                try:
                    result = await submission.executor(row_id)
                    if result is False:
                        failed_rows += 1
                    else:
                        completed_rows += 1
                except Exception:
                    failed_rows += 1

                if started.id in self._cancelled_jobs or submission.job_id in self._cancelled_jobs:
                    await self._finalize_cancel(started, completed_rows, failed_rows)
                    return

                await self._repository.save(
                    started.model_copy(
                        update={
                            "completed_rows": completed_rows,
                            "failed_rows": failed_rows,
                        }
                    )
                )
                await self._publish(
                    JobProgress(
                        job_id=started.id or submission.job_id,
                        job_type=started.job_type,
                        row_id=row_id,
                        completed_rows=completed_rows,
                        failed_rows=failed_rows,
                    )
                )

            final_state = (
                JobState.COMPLETED if failed_rows == 0 else JobState.COMPLETED_WITH_ERRORS
            )
            finished = await self._repository.save(
                started.model_copy(
                    update={
                        "state": final_state.value,
                        "completed_rows": completed_rows,
                        "failed_rows": failed_rows,
                        "finished_at": _utc_now(),
                    }
                )
            )
            await self._publish(
                JobCompleted(
                    job_id=finished.id or submission.job_id,
                    job_type=finished.job_type,
                    state=finished.state,
                    completed_rows=completed_rows,
                    failed_rows=failed_rows,
                )
            )
        except Exception as exc:
            finished = await self._repository.save(
                started.model_copy(
                    update={
                        "state": JobState.FAILED.value,
                        "error_message": str(exc),
                        "finished_at": _utc_now(),
                    }
                )
            )
            await self._publish(
                JobFailed(
                    job_id=finished.id or submission.job_id,
                    job_type=finished.job_type,
                    error_message=str(exc),
                )
            )

    async def _finalize_cancel(self, job: Job, completed_rows: int, failed_rows: int) -> Job:
        return await self._repository.save(
            job.model_copy(
                update={
                    "state": JobState.CANCELLED.value,
                    "completed_rows": completed_rows,
                    "failed_rows": failed_rows,
                    "finished_at": _utc_now(),
                }
            )
        )

    async def _wait_if_paused(self, job_id: int) -> None:
        async with self._pause_condition:
            while job_id in self._paused_jobs and job_id not in self._cancelled_jobs:
                await self._pause_condition.wait()

    async def _require_job(self, job_id: int) -> Job:
        job = await self._repository.get(job_id)
        if job is None:
            raise ValueError(f"Unknown job id: {job_id}")
        return job

    async def _publish(self, event: object) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(event)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_target_row_ids(target_row_ids: str) -> Iterable[int]:
    for chunk in target_row_ids.replace(";", ",").split(","):
        text = chunk.strip()
        if not text:
            continue
        yield int(text)
