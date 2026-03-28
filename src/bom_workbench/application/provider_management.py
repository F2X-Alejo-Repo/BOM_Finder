"""Provider management use cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from ..domain.entities import ProviderConfig
from ..domain.ports import (
    ChatConfig,
    ConnectionTestResult,
    IProviderAdapter,
    IProviderConfigRepository,
    ISecretStore,
    ModelInfo,
    ProviderCapabilities,
)

__all__ = [
    "ProviderAdapterRegistration",
    "ProviderManagementService",
    "ProviderRuntimeConfig",
    "ProviderState",
]


@dataclass(slots=True, frozen=True)
class ProviderAdapterRegistration:
    provider: str
    adapter: IProviderAdapter


@dataclass(slots=True, frozen=True)
class ProviderState:
    provider: str
    capabilities: ProviderCapabilities
    has_stored_key: bool = False
    config: ProviderConfig | None = None


@dataclass(slots=True, frozen=True)
class ProviderRuntimeConfig:
    provider: str
    model: str
    api_key: str
    reasoning_effort: str | None = None
    temperature: float | None = None
    timeout_seconds: int = 60
    max_retries: int = 3
    max_concurrent: int = 5
    privacy_level: str = "full"
    manual_approval: bool = False

    def to_chat_config(self, *, system_prompt: str = "", max_tokens: int = 4096) -> ChatConfig:
        return ChatConfig(
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=max_tokens,
            timeout_seconds=self.timeout_seconds,
            reasoning_effort=self.reasoning_effort,
            response_format="json_object",
            system_prompt=system_prompt,
        )


class ProviderManagementService:
    """Manage provider adapters and their stored credentials."""

    def __init__(
        self,
        secret_store: ISecretStore,
        config_repository: IProviderConfigRepository | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._config_repository = config_repository
        self._adapters: dict[str, IProviderAdapter] = {}

    def register_adapter(self, adapter: IProviderAdapter) -> ProviderAdapterRegistration:
        provider = adapter.get_name().strip()
        if not provider:
            raise ValueError("Adapter provider name is required.")
        self._adapters[provider] = adapter
        return ProviderAdapterRegistration(provider=provider, adapter=adapter)

    def list_providers(self) -> list[str]:
        return sorted(self._adapters)

    def get_adapter(self, provider: str) -> IProviderAdapter:
        try:
            return self._adapters[provider]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {provider}") from exc

    async def store_provider_key(self, provider: str, api_key: str) -> None:
        self._require_adapter(provider)
        await self._secret_store.store_key(provider, api_key)

    async def retrieve_provider_key(self, provider: str) -> str | None:
        self._require_adapter(provider)
        return await self._secret_store.get_key(provider)

    async def delete_provider_key(self, provider: str) -> None:
        self._require_adapter(provider)
        await self._secret_store.delete_key(provider)

    async def test_provider_connection(self, provider: str, api_key: str) -> ConnectionTestResult:
        adapter = self._require_adapter(provider)
        return await adapter.test_connection(api_key)

    async def discover_models(self, provider: str, api_key: str) -> list[ModelInfo]:
        adapter = self._require_adapter(provider)
        return await adapter.discover_models(api_key)

    def get_capabilities(self, provider: str) -> ProviderCapabilities:
        adapter = self._require_adapter(provider)
        return adapter.get_capabilities()

    async def save_provider_config(
        self,
        provider: str,
        payload: Mapping[str, Any],
    ) -> ProviderConfig | None:
        if self._config_repository is None:
            return None

        normalized_provider = provider.strip().lower()
        self._require_adapter(normalized_provider)
        existing = await self._config_repository.get_by_provider(normalized_provider)
        available_models = self._coerce_model_list(payload.get("available_models"))
        selected_model = str(
            payload.get("selected_model", existing.selected_model if existing else "")
        ).strip()
        if selected_model and selected_model not in available_models:
            available_models.append(selected_model)
        cached_models = (
            json.dumps(available_models, ensure_ascii=True, separators=(",", ":"))
            if available_models
            else (existing.cached_models if existing is not None else "")
        )
        models_cached_at = (
            self._utc_now() if available_models else (existing.models_cached_at if existing else None)
        )
        config = ProviderConfig(
            id=existing.id if existing is not None else None,
            provider_name=normalized_provider,
            enabled=bool(payload.get("enabled", existing.enabled if existing else False)),
            auth_method=existing.auth_method if existing is not None else "api_key",
            selected_model=selected_model,
            cached_models=cached_models,
            models_cached_at=models_cached_at,
            timeout_seconds=self._coerce_int(
                payload.get("timeout_seconds"),
                fallback=existing.timeout_seconds if existing is not None else 60,
            ),
            max_retries=self._coerce_int(
                payload.get("max_retries"),
                fallback=existing.max_retries if existing is not None else 3,
            ),
            max_concurrent=self._coerce_int(
                payload.get("max_concurrent"),
                fallback=existing.max_concurrent if existing is not None else 5,
            ),
            temperature=self._coerce_float(
                payload.get("temperature"),
                fallback=existing.temperature if existing is not None else None,
            ),
            reasoning_effort=self._coerce_reasoning_effort(
                payload.get("reasoning_mode", existing.reasoning_effort if existing else "")
            ),
            privacy_level=str(
                payload.get("privacy_level", existing.privacy_level if existing else "full")
            ).strip()
            or "full",
            manual_approval=bool(
                payload.get("manual_approval", existing.manual_approval if existing else False)
            ),
            extra_config=existing.extra_config if existing is not None else "",
            created_at=existing.created_at if existing is not None else self._utc_now(),
        )
        return await self._config_repository.save(config)

    async def get_provider_config(self, provider: str) -> ProviderConfig | None:
        if self._config_repository is None:
            return None
        return await self._config_repository.get_by_provider(provider.strip().lower())

    async def list_provider_configs(self) -> list[ProviderConfig]:
        if self._config_repository is None:
            return []
        return await self._config_repository.list_all()

    async def list_enabled_runtime_configs(self) -> list[ProviderRuntimeConfig]:
        if self._config_repository is None:
            return []

        runtimes: list[ProviderRuntimeConfig] = []
        for config in await self._config_repository.list_enabled():
            provider = config.provider_name.strip().lower()
            if provider not in self._adapters:
                continue
            api_key = await self._secret_store.get_key(provider)
            if not api_key or not config.selected_model.strip():
                continue
            runtimes.append(
                ProviderRuntimeConfig(
                    provider=provider,
                    model=config.selected_model.strip(),
                    api_key=api_key,
                    reasoning_effort=config.reasoning_effort.strip() or None,
                    temperature=config.temperature,
                    timeout_seconds=max(10, int(config.timeout_seconds or 60)),
                    max_retries=max(1, int(config.max_retries or 3)),
                    max_concurrent=max(1, int(config.max_concurrent or 1)),
                    privacy_level=config.privacy_level.strip() or "full",
                    manual_approval=bool(config.manual_approval),
                )
            )
        return runtimes

    async def describe_provider(self, provider: str) -> ProviderState:
        adapter = self._require_adapter(provider)
        has_stored_key = (await self._secret_store.get_key(provider)) is not None
        return ProviderState(
            provider=provider,
            capabilities=adapter.get_capabilities(),
            has_stored_key=has_stored_key,
            config=await self.get_provider_config(provider),
        )

    def build_llm_enrichment_stage(self):
        """Expose the default grounded LLM enrichment stage for app wiring."""

        from .llm_enrichment import build_grounded_llm_enrichment_stage

        return build_grounded_llm_enrichment_stage(self)

    def _require_adapter(self, provider: str) -> IProviderAdapter:
        try:
            return self._adapters[provider]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {provider}") from exc

    def _coerce_model_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return [text]
            value = parsed

        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _coerce_reasoning_effort(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in {"auto", "default"}:
            return ""
        return text

    def _coerce_int(self, value: Any, *, fallback: int) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return fallback

    def _coerce_float(self, value: Any, *, fallback: float | None) -> float | None:
        if value is None or value == "":
            return fallback
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return fallback
        return fallback

    def _utc_now(self) -> datetime:
        return datetime.now(UTC)
