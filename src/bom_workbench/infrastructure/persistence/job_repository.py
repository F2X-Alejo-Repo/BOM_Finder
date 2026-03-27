"""SQLite implementation of the tracked job repository."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from bom_workbench.domain.enums import JobState
from bom_workbench.domain.ports import IJobRepository

from .database import create_engine_from_settings, create_session_factory
from .models import Job

__all__ = ["SqliteJobRepository"]


def _coerce_job_state(value: Any) -> JobState:
    """Normalize supported job-state inputs to a JobState value."""

    if isinstance(value, JobState):
        return value

    if value is None:
        raise ValueError("job state cannot be None")

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("job state cannot be empty")

        lowered = text.lower()
        try:
            return JobState(lowered)
        except ValueError:
            member = JobState.__members__.get(text.upper())
            if member is not None:
                return member

    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, str):
        return _coerce_job_state(enum_value)

    enum_name = getattr(value, "name", None)
    if isinstance(enum_name, str):
        member = JobState.__members__.get(enum_name.strip().upper())
        if member is not None:
            return member

    raise ValueError(f"Unsupported job state value: {value!r}")


class SqliteJobRepository(IJobRepository):
    """Async job repository backed by a synchronous SQLite SQLModel session."""

    def __init__(
        self,
        engine: Engine | None = None,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        if session_factory is not None:
            self._session_factory = session_factory
        else:
            resolved_engine = engine or create_engine_from_settings()
            self._session_factory = create_session_factory(resolved_engine)

    async def save(self, job: Job) -> Job:
        return self._save_sync(job)

    async def get(self, job_id: int) -> Job | None:
        return self._get_sync(job_id)

    async def list_by_state(self, state: JobState) -> list[Job]:
        return self._list_by_state_sync(state)

    async def list_by_project(self, project_id: int) -> list[Job]:
        return self._list_by_project_sync(project_id)

    async def list_recent(self, limit: int = 50) -> list[Job]:
        return self._list_recent_sync(limit)

    def _save_sync(self, job: Job) -> Job:
        normalized_state = _coerce_job_state(job.state)
        payload = job.model_dump()
        payload["state"] = normalized_state.value

        with self._session_factory() as session:
            try:
                if job.id is None:
                    persisted = Job(**payload)
                    session.add(persisted)
                else:
                    persisted = session.get(Job, job.id)
                    if persisted is None:
                        persisted = Job(**payload)
                        session.add(persisted)
                    else:
                        for key, value in payload.items():
                            if key in {"id", "created_at"}:
                                continue
                            setattr(persisted, key, value)

                session.commit()
                session.refresh(persisted)
                return persisted
            except Exception:
                session.rollback()
                raise

    def _get_sync(self, job_id: int) -> Job | None:
        with self._session_factory() as session:
            return session.get(Job, job_id)

    def _list_by_state_sync(self, state: JobState) -> list[Job]:
        normalized_state = _coerce_job_state(state)
        statement = (
            select(Job)
            .where(Job.state == normalized_state.value)
            .order_by(Job.created_at.desc(), Job.id.desc())
        )

        with self._session_factory() as session:
            return list(session.exec(statement).all())

    def _list_by_project_sync(self, project_id: int) -> list[Job]:
        statement = (
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc(), Job.id.desc())
        )

        with self._session_factory() as session:
            return list(session.exec(statement).all())

    def _list_recent_sync(self, limit: int = 50) -> list[Job]:
        normalized_limit = max(0, int(limit))
        statement = (
            select(Job)
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(normalized_limit)
        )

        with self._session_factory() as session:
            return list(session.exec(statement).all())
