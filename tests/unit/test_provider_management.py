from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from bom_workbench.application.provider_management import ProviderManagementService
from bom_workbench.domain.ports import ConnectionTestResult, ModelInfo, ProviderCapabilities


@dataclass
class FakeSecretStore:
    values: dict[str, str] = field(default_factory=dict)

    async def store_key(self, provider: str, api_key: str) -> None:
        self.values[provider] = api_key

    async def get_key(self, provider: str) -> str | None:
        return self.values.get(provider)

    async def delete_key(self, provider: str) -> None:
        self.values.pop(provider, None)


class FakeAdapter:
    def __init__(self, name: str, capabilities: ProviderCapabilities) -> None:
        self._name = name
        self._capabilities = capabilities

    def get_name(self) -> str:
        return self._name

    def get_capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def test_connection(self, api_key: str) -> ConnectionTestResult:
        return ConnectionTestResult(success=api_key == "good", message="ok", provider=self._name)

    async def discover_models(self, api_key: str) -> list[ModelInfo]:
        return [ModelInfo(id="model-a", name="Model A", provider=self._name)]

    async def chat(self, messages, config):  # pragma: no cover - unused fake API
        raise NotImplementedError

    async def chat_structured(self, messages, response_schema, config):  # pragma: no cover - unused fake API
        raise NotImplementedError


def test_provider_management_registers_and_uses_secret_store() -> None:
    async def scenario() -> None:
        secret_store = FakeSecretStore()
        service = ProviderManagementService(secret_store)
        adapter = FakeAdapter("openai", ProviderCapabilities(supports_model_discovery=True))

        service.register_adapter(adapter)
        await service.store_provider_key("openai", "secret")

        assert service.list_providers() == ["openai"]
        assert await service.retrieve_provider_key("openai") == "secret"
        assert service.get_capabilities("openai").supports_model_discovery is True

    asyncio.run(scenario())

def test_provider_management_can_test_and_discover_models() -> None:
    async def scenario() -> None:
        service = ProviderManagementService(FakeSecretStore())
        adapter = FakeAdapter("openai", ProviderCapabilities())
        service.register_adapter(adapter)

        result = await service.test_provider_connection("openai", "good")
        models = await service.discover_models("openai", "good")

        assert result.success is True
        assert models[0].id == "model-a"

    asyncio.run(scenario())

def test_provider_management_describe_provider_reflects_stored_key() -> None:
    async def scenario() -> None:
        secret_store = FakeSecretStore(values={"openai": "secret"})
        service = ProviderManagementService(secret_store)
        service.register_adapter(FakeAdapter("openai", ProviderCapabilities(supports_streaming=True)))

        state = await service.describe_provider("openai")

        assert state.provider == "openai"
        assert state.has_stored_key is True
        assert state.capabilities.supports_streaming is True

    asyncio.run(scenario())
