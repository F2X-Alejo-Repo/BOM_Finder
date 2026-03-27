"""SQLite repository for BOM projects and rows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlmodel import Session, select

from ...domain.entities import BomProject, BomRow
from ...domain.ports import IBomRepository

__all__ = ["SqliteBomRepository"]


class SqliteBomRepository(IBomRepository):
    """SQLModel-backed persistence adapter for BOM domain entities."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def save_project(self, project: BomProject) -> BomProject:
        with self._session_factory() as session:
            saved = self._save_project(session, project)
            session.commit()
            session.refresh(saved)
            return saved

    async def get_project(self, project_id: int) -> BomProject | None:
        with self._session_factory() as session:
            statement = select(BomProject).where(BomProject.id == project_id)
            return session.exec(statement).one_or_none()

    async def list_projects(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BomProject]:
        with self._session_factory() as session:
            statement = (
                select(BomProject)
                .order_by(BomProject.created_at.asc(), BomProject.id.asc())
                .limit(limit)
                .offset(offset)
            )
            return list(session.exec(statement).all())

    async def delete_project(self, project_id: int) -> None:
        with self._session_factory() as session:
            row_statement = select(BomRow).where(BomRow.project_id == project_id)
            for row in session.exec(row_statement).all():
                session.delete(row)

            project_statement = select(BomProject).where(BomProject.id == project_id)
            project = session.exec(project_statement).one_or_none()
            if project is not None:
                session.delete(project)

            session.commit()

    async def save_row(self, row: BomRow) -> BomRow:
        with self._session_factory() as session:
            saved = self._save_row(session, row)
            session.commit()
            session.refresh(saved)
            return saved

    async def get_row(self, row_id: int) -> BomRow | None:
        with self._session_factory() as session:
            statement = select(BomRow).where(BomRow.id == row_id)
            return session.exec(statement).one_or_none()

    async def list_rows_by_project(self, project_id: int) -> list[BomRow]:
        with self._session_factory() as session:
            statement = (
                select(BomRow)
                .where(BomRow.project_id == project_id)
                .order_by(BomRow.original_row_index.asc(), BomRow.id.asc())
            )
            return list(session.exec(statement).all())

    async def list_rows_by_state(self, project_id: int, state: str) -> list[BomRow]:
        with self._session_factory() as session:
            statement = (
                select(BomRow)
                .where(
                    BomRow.project_id == project_id,
                    BomRow.row_state == state,
                )
                .order_by(BomRow.original_row_index.asc(), BomRow.id.asc())
            )
            return list(session.exec(statement).all())

    async def delete_row(self, row_id: int) -> None:
        with self._session_factory() as session:
            statement = select(BomRow).where(BomRow.id == row_id)
            row = session.exec(statement).one_or_none()
            if row is not None:
                session.delete(row)
                session.commit()

    def _save_project(self, session: Session, project: BomProject) -> BomProject:
        if project.id is None:
            session.add(project)
            project.updated_at = self._utc_now()
            return project

        statement = select(BomProject).where(BomProject.id == project.id)
        existing = session.exec(statement).one_or_none()
        if existing is None:
            session.add(project)
            project.updated_at = self._utc_now()
            return project

        payload = project.model_dump(
            exclude={"id", "rows", "created_at", "updated_at"},
            mode="python",
        )
        for field_name, value in payload.items():
            setattr(existing, field_name, value)
        existing.updated_at = self._utc_now()
        return existing

    def _save_row(self, session: Session, row: BomRow) -> BomRow:
        if row.id is None:
            session.add(row)
            row.updated_at = self._utc_now()
            return row

        statement = select(BomRow).where(BomRow.id == row.id)
        existing = session.exec(statement).one_or_none()
        if existing is None:
            session.add(row)
            row.updated_at = self._utc_now()
            return row

        payload = row.model_dump(
            exclude={"id", "project", "created_at", "updated_at"},
            mode="python",
        )
        for field_name, value in payload.items():
            setattr(existing, field_name, value)
        existing.updated_at = self._utc_now()
        return existing

    def _utc_now(self) -> datetime:
        return datetime.now(UTC)
