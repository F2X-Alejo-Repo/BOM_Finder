"""Tests for provider runtime configuration hydration and merging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from bom_workbench.application.provider_runtime_config import (
    ProviderRuntimeConfigService,
)
from bom_workbench.domain.entities import ProviderConfig


@dataclass
class FakeProviderConfigRepository:
    configs: dict[str, ProviderConfig] = field(default_factory=dict)

    async def save(self, config: ProviderConfig) -> ProviderConfig:
        self.configs[config.provider_name] = config
        return config

    async def get_by_provider(self, provider_name: str) -> ProviderConfig | None:
        return self.configs.get(provider_name.strip().lower())

    async def list_all(self) -> list[ProviderConfig]:
        return list(self.configs.values())

    async def list_enabled(self) -> list[ProviderConfig]:
        return [config for config in self.configs.values() if config.enabled]


@pytest.mark.anyio
async def test_provider_runtime_config_service_preserves_existing_values_without_hydration() -> None:
    repository = FakeProviderConfigRepository(
        configs={
            "openai": ProviderConfig(
                provider_name="openai",
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
        }
    )
    service = ProviderRuntimeConfigService(repository)

    saved = await service.save_provider_settings(
        {
            "openai": {
                "enabled": False,
                "selected_model": "gpt-5",
                "reasoning_mode": "High",
            }
        }
    )

    assert len(saved) == 1
    persisted = saved[0]
    assert persisted.enabled is False
    assert persisted.selected_model == "gpt-5"
    assert persisted.timeout_seconds == 90
    assert persisted.reasoning_effort == "high"
    assert persisted.cached_models == '["gpt-4.1-mini","gpt-5"]'


@pytest.mark.anyio
async def test_provider_runtime_config_service_round_trips_hydrated_runtime_defaults() -> None:
    repository = FakeProviderConfigRepository()
    service = ProviderRuntimeConfigService(repository)

    hydrated_payload = {
        "openai": {
            "provider": "openai",
            "enabled": False,
            "selected_model": "gpt-5",
            "reasoning_mode": "High",
            "runtime_defaults": {
                "cached_models": ["gpt-4.1-mini", "gpt-5"],
                "models_cached_at": "2026-03-01T12:30:00+00:00",
                "timeout_seconds": 90,
                "max_retries": 4,
                "max_concurrent": 2,
                "temperature": 0.2,
                "reasoning_effort": "high",
                "privacy_level": "minimal",
                "manual_approval": True,
                "auth_method": "api_key",
                "extra_config": {"profile": "prod"},
            },
        }
    }

    saved = await service.save_provider_settings(hydrated_payload)
    assert len(saved) == 1

    persisted = saved[0]
    assert persisted.provider_name == "openai"
    assert persisted.enabled is False
    assert persisted.selected_model == "gpt-5"
    assert persisted.timeout_seconds == 90
    assert persisted.max_retries == 4
    assert persisted.max_concurrent == 2
    assert persisted.temperature == 0.2
    assert persisted.reasoning_effort == "high"
    assert persisted.privacy_level == "minimal"
    assert persisted.manual_approval is True
    assert persisted.extra_config == '{"profile":"prod"}'

    loaded = await service.load_provider_settings()
    assert loaded["openai"]["enabled"] is False
    assert loaded["openai"]["selected_model"] == "gpt-5"
    assert loaded["openai"]["reasoning_mode"] == "High"
    assert loaded["openai"]["cached_models"] == ["gpt-4.1-mini", "gpt-5"]
    assert loaded["openai"]["timeout_seconds"] == 90
    assert loaded["openai"]["max_retries"] == 4
    assert loaded["openai"]["max_concurrent"] == 2
