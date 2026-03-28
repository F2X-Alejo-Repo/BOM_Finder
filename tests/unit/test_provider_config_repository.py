"""Tests for provider runtime configuration persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bom_workbench.domain.entities import ProviderConfig
from bom_workbench.infrastructure.persistence.database import (
    DatabaseSettings,
    create_db_and_tables,
    create_engine_from_settings,
    create_session_factory,
)
from bom_workbench.infrastructure.persistence.provider_config_repository import (
    SqliteProviderConfigRepository,
)


def _build_repository() -> SqliteProviderConfigRepository:
    engine = create_engine_from_settings(DatabaseSettings(in_memory=True))
    create_db_and_tables(engine)
    return SqliteProviderConfigRepository(create_session_factory(engine))


@pytest.mark.anyio
async def test_provider_config_repository_upserts_and_lists_enabled() -> None:
    repository = _build_repository()

    saved = await repository.save(
        ProviderConfig(
            provider_name="OpenAI",
            enabled=True,
            selected_model="gpt-4.1-mini",
            cached_models='["gpt-4.1-mini","gpt-5"]',
            models_cached_at=datetime(2026, 3, 1, 12, 30, tzinfo=UTC),
            timeout_seconds=90,
            max_retries=4,
            max_concurrent=2,
            temperature=0.2,
            reasoning_effort="medium",
            privacy_level="minimal",
            manual_approval=True,
            auth_method="api_key",
            extra_config='{"profile":"prod"}',
        )
    )

    assert saved.provider_name == "openai"
    assert saved.id is not None

    updated = await repository.save(
        saved.model_copy(
            update={
                "enabled": False,
                "selected_model": "gpt-5",
            }
        )
    )

    assert updated.id == saved.id
    assert updated.provider_name == "openai"
    assert updated.enabled is False
    assert updated.selected_model == "gpt-5"

    loaded = await repository.get_by_provider("OPENAI")
    assert loaded is not None
    assert loaded.provider_name == "openai"
    assert loaded.selected_model == "gpt-5"

    assert await repository.list_enabled() == []
    all_configs = await repository.list_all()
    assert len(all_configs) == 1
