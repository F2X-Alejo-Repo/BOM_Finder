from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from bom_workbench.application import (
    EventBus,
    JobCancelled,
    JobCompleted,
    JobManager,
    JobProgress,
    JobQueued,
    JobStarted,
)
from bom_workbench.domain.entities import Job
from bom_workbench.domain.enums import JobState


@dataclass
class FakeJobRepository:
    jobs: dict[int, Job] = field(default_factory=dict)
    next_id: int = 1

    async def save(self, job: Job) -> Job:
        if job.id is None:
            job = job.model_copy(update={"id": self.next_id})
            self.next_id += 1
        self.jobs[job.id] = job
        return job

    async def get(self, job_id: int) -> Job | None:
        return self.jobs.get(job_id)

    async def list_by_state(self, state: JobState) -> list[Job]:
        return [job for job in self.jobs.values() if job.state == state.value]

    async def list_by_project(self, project_id: int) -> list[Job]:
        return [job for job in self.jobs.values() if job.project_id == project_id]

    async def list_recent(self, limit: int = 50) -> list[Job]:
        return list(self.jobs.values())[:limit]


async def _wait_for_state(repo: FakeJobRepository, job_id: int, state: str) -> Job:
    for _ in range(200):
        job = await repo.get(job_id)
        assert job is not None
        if job.state == state:
            return job
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach state {state!r}")


def test_job_manager_completes_successfully() -> None:
    async def scenario() -> None:
        repo = FakeJobRepository()
        bus = EventBus[object]()
        events: list[object] = []
        bus.subscribe(events.append)
        manager = JobManager(repo, event_bus=bus, max_concurrency=1)

        job = await manager.submit(
            Job(job_type="enrich", target_row_ids="1,2,3", total_rows=3),
            executor=lambda row_id: asyncio.sleep(0, result=True),
        )

        final = await _wait_for_state(repo, job.id, JobState.COMPLETED.value)
        assert final.completed_rows == 3
        assert final.failed_rows == 0
        assert any(isinstance(event, JobQueued) for event in events)
        assert any(isinstance(event, JobStarted) for event in events)
        assert any(isinstance(event, JobProgress) for event in events)
        assert any(
            isinstance(event, JobCompleted) and event.state == JobState.COMPLETED.value
            for event in events
        )

        await manager.close()

    asyncio.run(scenario())


def test_job_manager_marks_partial_failures_as_completed_with_errors() -> None:
    async def scenario() -> None:
        repo = FakeJobRepository()
        manager = JobManager(repo, max_concurrency=1)

        async def executor(row_id: int) -> bool | None:
            if row_id == 2:
                return False
            if row_id == 3:
                raise RuntimeError("boom")
            return True

        job = await manager.submit(
            Job(job_type="enrich", target_row_ids="1,2,3", total_rows=3),
            executor=executor,
        )

        final = await _wait_for_state(repo, job.id, JobState.COMPLETED_WITH_ERRORS.value)
        assert final.completed_rows == 1
        assert final.failed_rows == 2

        await manager.close()

    asyncio.run(scenario())


def test_job_manager_cancels_running_job() -> None:
    async def scenario() -> None:
        repo = FakeJobRepository()
        bus = EventBus[object]()
        events: list[object] = []
        bus.subscribe(events.append)
        manager = JobManager(repo, event_bus=bus, max_concurrency=1)
        unblock = asyncio.Event()

        async def executor(row_id: int) -> bool | None:
            await unblock.wait()
            return True

        job = await manager.submit(
            Job(job_type="export", target_row_ids="1,2", total_rows=2),
            executor=executor,
        )
        await _wait_for_state(repo, job.id, JobState.RUNNING.value)

        await manager.cancel(job.id)
        unblock.set()

        final = await _wait_for_state(repo, job.id, JobState.CANCELLED.value)
        assert final.state == JobState.CANCELLED.value
        assert any(isinstance(event, JobCancelled) for event in events)

        await manager.close()

    asyncio.run(scenario())
