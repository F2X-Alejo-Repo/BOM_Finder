# 09 — Job Management

## Job Manager Architecture

The `JobManager` is the central async orchestrator for all background work.

```
User Action (e.g., "Enrich All")
    │
    ▼
JobManager.submit(job_request)
    │
    ▼
┌───────────────────────────────┐
│ JOB QUEUE                     │
│ (asyncio.Queue)               │
│                               │
│  [J-042: enrich_batch, 142]   │
│  [J-043: find_parts, 1]      │
│  [J-044: export, 1]          │
└──────────┬────────────────────┘
           │
           ▼
┌───────────────────────────────┐
│ WORKER LOOP                   │
│ (bounded by semaphore)        │
│                               │
│ Semaphore(max_concurrent=5)   │
│                               │
│ ┌─────────┐ ┌─────────┐      │
│ │Worker 1 │ │Worker 2 │ ...  │
│ │Row 1    │ │Row 2    │      │
│ └─────────┘ └─────────┘      │
└──────────┬────────────────────┘
           │
           ▼
     Events emitted:
     - job_state_changed
     - row_enriched
     - job_progress_updated
     - job_completed
     - job_failed
```

## Job State Machine

```
PENDING ──submit──► QUEUED ──worker picks up──► RUNNING
                                                   │
                                          ┌────────┼────────┐
                                          ▼        ▼        ▼
                                     COMPLETED  FAILED   CANCELLED
                                                   │
                                                   ▼
                                              (retry) → QUEUED

RUNNING ──pause──► PAUSED ──resume──► RUNNING
```

## JobManager Class

```python
class JobManager:
    """Manages async job lifecycle with bounded concurrency."""

    def __init__(
        self,
        job_repository: IJobRepository,
        event_bus: EventBus,
        max_concurrent: int = 5,
    ):
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: dict[int, asyncio.Task] = {}
        self._job_repo = job_repository
        self._event_bus = event_bus
        self._paused: set[int] = set()
        self._running = False

    async def start(self) -> None:
        """Start the worker loop. Called once at app startup."""
        self._running = True
        asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """Gracefully stop all workers."""
        self._running = False
        # Cancel all active tasks
        for task in self._active_tasks.values():
            task.cancel()

    async def submit(self, job: Job, executor: Callable) -> Job:
        """Submit a new job to the queue."""
        job.state = JobState.QUEUED
        await self._job_repo.save(job)
        await self._queue.put((job, executor))
        self._event_bus.emit("job_state_changed", job)
        return job

    async def pause(self, job_id: int) -> None:
        """Pause a running job (it will finish current row, then stop)."""
        self._paused.add(job_id)

    async def resume(self, job_id: int) -> None:
        """Resume a paused job."""
        self._paused.discard(job_id)

    async def cancel(self, job_id: int) -> None:
        """Cancel a running or queued job."""
        if job_id in self._active_tasks:
            self._active_tasks[job_id].cancel()

    async def retry_failed(self, job_id: int, executor: Callable) -> None:
        """Re-queue only the failed rows of a job."""
        job = await self._job_repo.get(job_id)
        # Create new job with only failed row IDs
        ...

    async def _worker_loop(self) -> None:
        """Main loop: dequeue jobs, respect semaphore, execute."""
        while self._running:
            job, executor = await self._queue.get()
            asyncio.create_task(self._execute_job(job, executor))

    async def _execute_job(self, job: Job, executor: Callable) -> None:
        """Execute a single job with concurrency control."""
        async with self._semaphore:
            job.state = JobState.RUNNING
            job.started_at = datetime.utcnow()
            await self._job_repo.save(job)
            self._event_bus.emit("job_state_changed", job)

            try:
                row_ids = json.loads(job.target_row_ids)
                for row_id in row_ids:
                    # Check pause/cancel
                    if job.id in self._paused:
                        job.state = JobState.PAUSED
                        await self._job_repo.save(job)
                        self._event_bus.emit("job_state_changed", job)
                        # Wait until resumed
                        while job.id in self._paused:
                            await asyncio.sleep(0.5)
                        job.state = JobState.RUNNING

                    # Execute for single row
                    try:
                        await executor(row_id)
                        job.completed_rows += 1
                    except Exception as e:
                        job.failed_rows += 1
                        logger.error("row_failed", row_id=row_id, error=str(e))

                    await self._job_repo.save(job)
                    self._event_bus.emit("job_progress_updated", job)

                job.state = JobState.COMPLETED if job.failed_rows == 0 else JobState.COMPLETED
                job.finished_at = datetime.utcnow()
                job.duration_seconds = (job.finished_at - job.started_at).total_seconds()

            except asyncio.CancelledError:
                job.state = JobState.CANCELLED
            except Exception as e:
                job.state = JobState.FAILED
                job.error_message = str(e)
            finally:
                await self._job_repo.save(job)
                self._event_bus.emit("job_state_changed", job)
```

## Retry Strategy

Using `tenacity` for individual API calls within the executor:

```python
@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def call_provider(adapter: IProviderAdapter, messages, config) -> ProviderResponse:
    return await adapter.chat(messages, config)
```

**Retry hierarchy**:
1. **Per-API-call retry** (tenacity): handles transient HTTP errors (429, 500, 502, 503, timeouts)
2. **Per-row retry** (JobManager): if a row fails after all API retries, mark failed, continue to next row
3. **Per-job retry** (user action): user can "Retry Failed" to re-process only failed rows

## EventBus

```python
class EventBus:
    """Lightweight pub/sub for decoupled communication between layers."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callable) -> None:
        self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        self._subscribers[event].remove(callback)

    def emit(self, event: str, *args, **kwargs) -> None:
        for callback in self._subscribers[event]:
            # If in Qt context, use QMetaObject.invokeMethod for thread safety
            callback(*args, **kwargs)
```

## Job Persistence

Jobs are persisted to SQLite so that:
- App restart shows job history
- Partially completed jobs can be identified for resumption
- Failed rows are tracked for retry
- Export of failure reports is possible

The `IJobRepository` interface:

```python
class IJobRepository(ABC):
    @abstractmethod
    async def save(self, job: Job) -> Job: ...

    @abstractmethod
    async def get(self, job_id: int) -> Job | None: ...

    @abstractmethod
    async def list_by_state(self, state: JobState) -> list[Job]: ...

    @abstractmethod
    async def list_by_project(self, project_id: int) -> list[Job]: ...

    @abstractmethod
    async def list_recent(self, limit: int = 50) -> list[Job]: ...
```

## Concurrency Control

- Global semaphore limits total concurrent API calls
- `max_concurrent` is configurable per provider in `ProviderConfig`
- The effective concurrency = min(global_max, provider_max)
- Each enrichment row = 1 semaphore slot (even if it makes multiple API calls internally, they share the slot)
