"""Unit tests for app-level enrichment runtime selection."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bom_workbench.app import (
    _detect_provider_api_key,
    _provider_default_model,
    _resolve_enrichment_job_identity,
    _resolve_enrichment_job_plan,
    _resolve_llm_stage,
    _tier1_openai_worker_cap,
)


@dataclass(slots=True)
class _RuntimeConfig:
    provider: str
    model: str
    manual_approval: bool = False
    max_concurrent: int = 5


@dataclass(slots=True)
class _RuntimeService:
    runtimes: list[_RuntimeConfig]

    async def list_enabled_runtime_configs(self) -> list[_RuntimeConfig]:
        return list(self.runtimes)


@dataclass(slots=True)
class _StageService:
    stage: object
    calls: list[object]

    def build_llm_enrichment_stage(self, provider_service: object) -> object:
        self.calls.append(provider_service)
        return self.stage


@dataclass(slots=True)
class _RepoStageService:
    stage: object
    calls: list[object]

    def build_llm_enrichment_stage(self, provider_config_repository: object) -> object:
        self.calls.append(provider_config_repository)
        return self.stage


@pytest.mark.anyio
async def test_resolve_enrichment_job_identity_prefers_first_approved_runtime() -> None:
    service = _RuntimeService(
        runtimes=[
            _RuntimeConfig(provider="openai", model="gpt-4.1-mini", manual_approval=True),
            _RuntimeConfig(provider="anthropic", model="claude-sonnet-4", manual_approval=False),
        ]
    )

    provider_name, model_name = await _resolve_enrichment_job_identity(service)

    assert provider_name == "anthropic"
    assert model_name == "claude-sonnet-4"


@pytest.mark.anyio
async def test_resolve_enrichment_job_identity_falls_back_without_active_runtime() -> None:
    service = _RuntimeService(
        runtimes=[
            _RuntimeConfig(provider="openai", model="gpt-4.1-mini", manual_approval=True),
        ]
    )

    provider_name, model_name = await _resolve_enrichment_job_identity(service)

    assert provider_name == "deterministic"
    assert model_name == "deterministic-parser"


@pytest.mark.anyio
async def test_resolve_enrichment_job_plan_uses_tier1_openai_worker_cap() -> None:
    service = _RuntimeService(
        runtimes=[
            _RuntimeConfig(
                provider="openai",
                model="gpt-4.1-mini",
                manual_approval=False,
                max_concurrent=5,
            ),
        ]
    )

    provider_name, model_name, row_concurrency = await _resolve_enrichment_job_plan(
        service,
        row_count=40,
    )

    assert provider_name == "openai"
    assert model_name == "gpt-4.1-mini"
    assert row_concurrency == 16


def test_tier1_openai_worker_cap_is_model_specific() -> None:
    assert _tier1_openai_worker_cap("openai", "gpt-4.1-mini") == 16
    assert _tier1_openai_worker_cap("openai", "unknown-model") == 0
    assert _tier1_openai_worker_cap("anthropic", "gpt-4.1-mini") == 0


def test_resolve_llm_stage_uses_service_hook_when_present() -> None:
    sentinel = object()
    service = _StageService(stage=sentinel, calls=[])

    resolved = _resolve_llm_stage(service)

    assert resolved is sentinel
    assert service.calls == [service]


def test_resolve_llm_stage_can_use_repository_hook_when_present() -> None:
    sentinel = object()
    repository = object()
    service = _RepoStageService(stage=sentinel, calls=[])

    resolved = _resolve_llm_stage(service, repository)

    assert resolved is sentinel
    assert service.calls == [repository]


def test_detect_provider_api_key_prefers_process_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-value")
    (tmp_path / ".env").write_text('OPENAI_API_KEY="sk-file-value"\n', encoding="utf-8")

    detected = _detect_provider_api_key("openai", search_roots=[tmp_path])

    assert detected == ("sk-env-value", "environment variable OPENAI_API_KEY")


def test_detect_provider_api_key_reads_dotenv_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BOM_WORKBENCH_OPENAI_API_KEY", raising=False)
    (tmp_path / ".env.local").write_text("OPENAI_API_KEY=sk-local-value\n", encoding="utf-8")

    detected = _detect_provider_api_key("openai", search_roots=[tmp_path])

    assert detected == ("sk-local-value", ".env.local (OPENAI_API_KEY)")


def test_provider_default_model_is_openai_specific() -> None:
    assert _provider_default_model("openai") == "gpt-4.1-mini"
    assert _provider_default_model("anthropic") == ""
