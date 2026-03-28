"""Async job manager with queued execution and bounded concurrency."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

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

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class RowExecutionResult:
    """Normalized executor result used by adaptive row scheduling."""

    success: bool
    latency_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    error_category: str = ""
    rate_limited: bool = False
    retry_after_seconds: float | None = None


RowExecutorResult = bool | None | RowExecutionResult
RowExecutor = Callable[[int], Awaitable[RowExecutorResult]]


@dataclass(slots=True, frozen=True)
class JobSubmission:
    """Payload stored in the internal queue."""

    job_id: int
    executor: RowExecutor
    row_concurrency: int = 1


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

    async def submit(
        self,
        job: Job,
        executor: RowExecutor,
        *,
        row_concurrency: int = 1,
    ) -> Job:
        """Persist a job as queued and schedule it for execution."""

        normalized_row_concurrency = max(1, int(row_concurrency or 1))
        persisted = await self._repository.save(
            job.model_copy(update={"state": JobState.QUEUED.value})
        )
        if persisted.id is None:
            raise RuntimeError("Saved job did not return an id.")

        await self._publish(JobQueued(persisted.id, persisted.job_type, persisted.total_rows))
        await self._queue.put(
            JobSubmission(
                persisted.id,
                executor,
                row_concurrency=normalized_row_concurrency,
            )
        )
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
        row_ids = list(_parse_target_row_ids(started.target_row_ids))

        try:
            row_queue: asyncio.Queue[int] = asyncio.Queue()
            for row_id in row_ids:
                row_queue.put_nowait(row_id)

            counter_lock = asyncio.Lock()
            adaptive_lock = asyncio.Lock()
            worker_cap = min(max(1, submission.row_concurrency), max(len(row_ids), 1))
            worker_count = worker_cap
            active_limit = min(worker_cap, 4) if worker_cap > 1 else 1
            in_flight = 0
            latency_window: deque[float] = deque(maxlen=8)
            successful_samples = 0
            cooldown_until = 0.0
            adaptive_condition = asyncio.Condition()

            async def process_row(row_id: int) -> RowExecutionResult:
                nonlocal completed_rows, failed_rows
                try:
                    result = self._normalize_row_result(await submission.executor(row_id))
                except Exception:
                    result = RowExecutionResult(success=False, error_category="executor_exception")

                async with counter_lock:
                    if result.success:
                        completed_rows += 1
                    else:
                        failed_rows += 1

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
                return result

            async def worker() -> None:
                nonlocal in_flight
                while True:
                    await self._wait_if_paused(started.id or submission.job_id)

                    async with adaptive_condition:
                        while True:
                            if (
                                started.id in self._cancelled_jobs
                                or submission.job_id in self._cancelled_jobs
                            ):
                                return
                            if row_queue.empty():
                                return
                            if in_flight < active_limit:
                                row_id = row_queue.get_nowait()
                                in_flight += 1
                                break
                            await adaptive_condition.wait()
                    try:
                        result = await process_row(row_id)
                    finally:
                        row_queue.task_done()
                        async with adaptive_condition:
                            in_flight -= 1
                            adaptive_condition.notify_all()
                    await update_adaptive_window(result)

            async def update_adaptive_window(result: RowExecutionResult) -> None:
                nonlocal active_limit, successful_samples, cooldown_until
                if worker_cap <= 1:
                    return

                now = time.monotonic()
                async with adaptive_lock:
                    if result.latency_ms > 0:
                        latency_window.append(result.latency_ms)

                    if result.rate_limited or result.error_category == "rate_limit":
                        next_limit = max(1, active_limit // 2)
                        retry_after = result.retry_after_seconds
                        if retry_after is None or retry_after <= 0:
                            retry_after = 2.0
                        cooldown_until = max(cooldown_until, now + min(retry_after, 30.0))
                        successful_samples = 0
                        if next_limit != active_limit:
                            active_limit = next_limit
                            async with adaptive_condition:
                                adaptive_condition.notify_all()
                        await self._publish_internal_log(
                            "adaptive_row_concurrency_backoff",
                            job_id=started.id or submission.job_id,
                            active_limit=active_limit,
                            worker_cap=worker_cap,
                            retry_after_seconds=retry_after,
                            error_category=result.error_category or "rate_limit",
                        )
                        return

                    if result.error_category in {"timeout", "network_error", "server_error"}:
                        if active_limit > 1:
                            active_limit -= 1
                            cooldown_until = max(cooldown_until, now + 2.0)
                            successful_samples = 0
                            async with adaptive_condition:
                                adaptive_condition.notify_all()
                            await self._publish_internal_log(
                                "adaptive_row_concurrency_slowdown",
                                job_id=started.id or submission.job_id,
                                active_limit=active_limit,
                                worker_cap=worker_cap,
                                error_category=result.error_category,
                            )
                        return

                    average_latency = (
                        sum(latency_window) / len(latency_window)
                        if latency_window
                        else result.latency_ms
                    )
                    if average_latency >= 12_000 and active_limit > 1:
                        active_limit -= 1
                        cooldown_until = max(cooldown_until, now + 2.0)
                        successful_samples = 0
                        async with adaptive_condition:
                            adaptive_condition.notify_all()
                        await self._publish_internal_log(
                            "adaptive_row_concurrency_latency_backoff",
                            job_id=started.id or submission.job_id,
                            active_limit=active_limit,
                            worker_cap=worker_cap,
                            average_latency_ms=round(average_latency, 2),
                        )
                        return

                    if (
                        result.success
                        and active_limit < worker_cap
                        and now >= cooldown_until
                        and average_latency > 0
                        and average_latency <= 7_500
                    ):
                        successful_samples += 1
                        threshold = 2 if active_limit < 4 else 4
                        if successful_samples >= threshold:
                            active_limit += 1
                            successful_samples = 0
                            async with adaptive_condition:
                                adaptive_condition.notify_all()
                            await self._publish_internal_log(
                                "adaptive_row_concurrency_increase",
                                job_id=started.id or submission.job_id,
                                active_limit=active_limit,
                                worker_cap=worker_cap,
                                average_latency_ms=round(average_latency, 2),
                            )

            workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
            try:
                await asyncio.gather(*workers)
            finally:
                for task in workers:
                    if not task.done():
                        task.cancel()
                for task in workers:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

            if started.id in self._cancelled_jobs or submission.job_id in self._cancelled_jobs:
                await self._finalize_cancel(started, completed_rows, failed_rows)
                return

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

    async def _publish_internal_log(self, event_name: str, **payload: Any) -> None:
        """Optional debug hook for adaptive scheduling internals."""

        logger.info(event_name, **payload)

    def _normalize_row_result(self, result: RowExecutorResult) -> RowExecutionResult:
        if isinstance(result, RowExecutionResult):
            return result
        return RowExecutionResult(success=result is not False)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _parse_target_row_ids(target_row_ids: str) -> Iterable[int]:
    for chunk in target_row_ids.replace(";", ",").split(","):
        text = chunk.strip()
        if not text:
            continue
        yield int(text)
