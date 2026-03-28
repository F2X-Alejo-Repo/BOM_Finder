"""SQLite persistence for provider runtime settings."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlmodel import Session, select

from ...domain.entities import ProviderConfig
from ...domain.ports import IProviderConfigRepository

__all__ = ["SqliteProviderConfigRepository"]


class SqliteProviderConfigRepository(IProviderConfigRepository):
    """Persist provider settings needed at runtime."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def save(self, config: ProviderConfig) -> ProviderConfig:
        with self._session_factory() as session:
            saved = self._save_sync(session, config)
            session.commit()
            session.refresh(saved)
            return saved

    async def get_by_provider(self, provider_name: str) -> ProviderConfig | None:
        with self._session_factory() as session:
            statement = select(ProviderConfig).where(
                ProviderConfig.provider_name == provider_name.strip().lower()
            )
            return session.exec(statement).one_or_none()

    async def list_all(self) -> list[ProviderConfig]:
        with self._session_factory() as session:
            statement = select(ProviderConfig).order_by(ProviderConfig.provider_name.asc())
            return list(session.exec(statement).all())

    async def list_enabled(self) -> list[ProviderConfig]:
        with self._session_factory() as session:
            statement = (
                select(ProviderConfig)
                .where(ProviderConfig.enabled.is_(True))
                .order_by(ProviderConfig.provider_name.asc())
            )
            return list(session.exec(statement).all())

    def _save_sync(self, session: Session, config: ProviderConfig) -> ProviderConfig:
        normalized_provider = config.provider_name.strip().lower()
        payload = config.model_dump(mode="python")
        payload["provider_name"] = normalized_provider

        if config.id is None:
            existing = session.exec(
                select(ProviderConfig).where(ProviderConfig.provider_name == normalized_provider)
            ).one_or_none()
            if existing is None:
                persisted = ProviderConfig(**payload)
                persisted.updated_at = self._utc_now()
                session.add(persisted)
                return persisted
        else:
            existing = session.get(ProviderConfig, config.id)
            if existing is None:
                existing = session.exec(
                    select(ProviderConfig).where(
                        ProviderConfig.provider_name == normalized_provider
                    )
                ).one_or_none()

        if existing is None:
            persisted = ProviderConfig(**payload)
            persisted.updated_at = self._utc_now()
            session.add(persisted)
            return persisted

        for key, value in payload.items():
            if key in {"id", "created_at", "updated_at"}:
                continue
            setattr(existing, key, value)
        existing.updated_at = self._utc_now()
        return existing

    def _utc_now(self) -> datetime:
        return datetime.now(UTC)
