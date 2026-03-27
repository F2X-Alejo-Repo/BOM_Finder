"""Provider management use cases."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.ports import (
    ConnectionTestResult,
    IProviderAdapter,
    ISecretStore,
    ModelInfo,
    ProviderCapabilities,
)

__all__ = ["ProviderAdapterRegistration", "ProviderManagementService", "ProviderState"]


@dataclass(slots=True, frozen=True)
class ProviderAdapterRegistration:
    provider: str
    adapter: IProviderAdapter


@dataclass(slots=True, frozen=True)
class ProviderState:
    provider: str
    capabilities: ProviderCapabilities
    has_stored_key: bool = False


class ProviderManagementService:
    """Manage provider adapters and their stored credentials."""

    def __init__(self, secret_store: ISecretStore) -> None:
        self._secret_store = secret_store
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

    async def describe_provider(self, provider: str) -> ProviderState:
        adapter = self._require_adapter(provider)
        has_stored_key = (await self._secret_store.get_key(provider)) is not None
        return ProviderState(
            provider=provider,
            capabilities=adapter.get_capabilities(),
            has_stored_key=has_stored_key,
        )

    def _require_adapter(self, provider: str) -> IProviderAdapter:
        try:
            return self._adapters[provider]
        except KeyError as exc:
            raise KeyError(f"Unknown provider: {provider}") from exc
