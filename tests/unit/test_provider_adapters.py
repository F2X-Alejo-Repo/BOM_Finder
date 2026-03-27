"""Unit tests for provider adapters."""

from __future__ import annotations

import httpx
import pytest

from bom_workbench.infrastructure.providers import (
    AnthropicProviderAdapter,
    OpenAIProviderAdapter,
)


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(
        "bom_workbench.infrastructure.providers.openai_adapter.httpx.AsyncClient",
        factory,
    )
    monkeypatch.setattr(
        "bom_workbench.infrastructure.providers.anthropic_adapter.httpx.AsyncClient",
        factory,
    )


@pytest.mark.anyio
async def test_openai_discover_models_parses_and_sorts_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.openai.com/v1/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "gpt-4o",
                        "display_name": "GPT-4o",
                        "created": 1_700_000_100,
                    },
                    {
                        "id": "gpt-4.1",
                        "name": "GPT-4.1",
                        "created": 1_700_000_000,
                    },
                ]
            },
        )

    _patch_async_client(monkeypatch, handler)

    adapter = OpenAIProviderAdapter()
    models = await adapter.discover_models("test-key")

    assert [model.id for model in models] == ["gpt-4.1", "gpt-4o"]
    assert models[0].provider == "openai"
    assert models[0].name == "GPT-4.1"
    assert models[0].created_at is not None


@pytest.mark.anyio
async def test_anthropic_discover_models_parses_context_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.anthropic.com/v1/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "claude-sonnet-4",
                        "display_name": "Claude Sonnet 4",
                        "context_window": 200_000,
                        "modalities": ["text", "image"],
                    },
                    {
                        "id": "claude-haiku-4",
                        "display_name": "Claude Haiku 4",
                        "context_window": 200_000,
                    },
                ]
            },
        )

    _patch_async_client(monkeypatch, handler)

    adapter = AnthropicProviderAdapter()
    models = await adapter.discover_models("test-key")

    assert [model.id for model in models] == [
        "claude-haiku-4",
        "claude-sonnet-4",
    ]
    assert models[1].provider == "anthropic"
    assert models[1].context_window == 200_000
    assert models[1].supports_vision is True


@pytest.mark.anyio
async def test_openai_test_connection_maps_http_failure_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://api.openai.com/v1/models")
        return httpx.Response(
            401,
            json={"error": {"message": "invalid_api_key"}},
        )

    _patch_async_client(monkeypatch, handler)

    adapter = OpenAIProviderAdapter()
    result = await adapter.test_connection("sk-test-secret")

    assert result.success is False
    assert result.provider == "openai"
    assert result.details["status_code"] == 401
    assert "sk-test-secret" not in result.message
    assert "invalid_api_key" not in result.message

