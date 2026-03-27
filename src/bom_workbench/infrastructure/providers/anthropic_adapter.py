"""Anthropic provider adapter."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from ...domain.ports import (
    ChatConfig,
    ConnectionTestResult,
    ModelInfo,
    ProviderCapabilities,
    ProviderResponse,
)
from .base import (
    build_timeout,
    model_from_payload,
    now_ms,
    response_usage_from_anthropic,
    safe_connection_result,
    safe_provider_response,
)

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_MODELS_PATH = "/v1/models"
ANTHROPIC_MESSAGES_PATH = "/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProviderAdapter:
    """Adapter for Anthropic model and messages APIs."""

    def __init__(self, base_url: str = ANTHROPIC_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    def get_name(self) -> str:
        return "anthropic"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_model_discovery=True,
            supports_reasoning_control=False,
            supports_structured_output=True,
            supports_tool_use=True,
            supports_batch=False,
            supports_streaming=True,
            supports_temperature=True,
            reasoning_control_name="",
            reasoning_levels=[],
        )

    async def test_connection(self, api_key: str) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(api_key),
                timeout=build_timeout(10.0),
            ) as client:
                response = await client.get(ANTHROPIC_MODELS_PATH)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else 0
            return safe_connection_result(
                provider=self.get_name(),
                success=False,
                message=f"Anthropic connection failed with HTTP {status_code}.",
                latency_ms=now_ms(start),
                details={"status_code": status_code},
            )
        except httpx.RequestError as exc:
            return safe_connection_result(
                provider=self.get_name(),
                success=False,
                message=f"Anthropic connection failed: {type(exc).__name__}.",
                latency_ms=now_ms(start),
                details={"error_type": type(exc).__name__},
            )

        return safe_connection_result(
            provider=self.get_name(),
            success=True,
            message="Anthropic connection successful.",
            latency_ms=now_ms(start),
        )

    async def discover_models(self, api_key: str) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(api_key),
                timeout=build_timeout(10.0),
            ) as client:
                response = await client.get(ANTHROPIC_MODELS_PATH)
                response.raise_for_status()
        except Exception:
            return []

        payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(models, list):
            return []

        discovered = [
            model_from_payload(provider=self.get_name(), payload=item)
            for item in models
            if isinstance(item, Mapping)
        ]
        return sorted(discovered, key=lambda model: model.id)

    async def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        config: ChatConfig,
    ) -> ProviderResponse:
        system_prompt, request_messages = self._split_messages(messages)
        system_prompt = self._merge_system_prompts(config.system_prompt, system_prompt)
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": request_messages,
            "max_tokens": config.max_tokens,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if config.temperature is not None:
            payload["temperature"] = config.temperature

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(config.api_key),
                timeout=build_timeout(config.timeout_seconds),
            ) as client:
                response = await client.post(ANTHROPIC_MESSAGES_PATH, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else 0
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=f"Anthropic chat failed with HTTP {status_code}.",
                raw_response={"status_code": status_code},
            )
        except httpx.RequestError as exc:
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=f"Anthropic chat failed: {type(exc).__name__}.",
                raw_response={"error_type": type(exc).__name__},
            )

        payload = response.json()
        content = self._extract_text(payload)
        if content is None:
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message="Anthropic response did not include assistant content.",
                raw_response=payload,
            )

        return safe_provider_response(
            content=content,
            model=config.model,
            provider=self.get_name(),
            latency_ms=now_ms(start),
            usage=response_usage_from_anthropic(payload),
            raw_response=payload,
        )

    async def chat_structured(
        self,
        messages: Sequence[Mapping[str, str]],
        response_schema: type[BaseModel],
        config: ChatConfig,
    ) -> ProviderResponse:
        schema_text = json.dumps(
            response_schema.model_json_schema(),
            indent=2,
            sort_keys=True,
        )
        structured_messages = list(messages)
        structured_system = self._merge_system_prompts(
            config.system_prompt,
            "Return only valid JSON that matches this schema:\n" + schema_text,
        )
        result = await self.chat(
            structured_messages,
            ChatConfig(
                api_key=config.api_key,
                model=config.model,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout_seconds=config.timeout_seconds,
                reasoning_effort=config.reasoning_effort,
                response_format=config.response_format,
                system_prompt=structured_system,
            ),
        )
        if not result.success:
            return result

        try:
            parsed = response_schema.model_validate_json(result.content)
        except Exception as exc:
            return safe_provider_response(
                content=result.content,
                model=config.model,
                provider=self.get_name(),
                latency_ms=result.latency_ms,
                success=False,
                error_message=(
                    "Anthropic structured response validation failed: "
                    f"{type(exc).__name__}."
                ),
                raw_response=result.raw_response,
                usage=result.usage,
            )

        return safe_provider_response(
            content=parsed.model_dump_json(),
            model=config.model,
            provider=self.get_name(),
            latency_ms=result.latency_ms,
            usage=result.usage,
            raw_response=result.raw_response,
        )

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def _split_messages(
        self,
        messages: Sequence[Mapping[str, str]],
    ) -> tuple[str, list[dict[str, str]]]:
        system_parts: list[str] = []
        normalized: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "system":
                if content:
                    system_parts.append(content)
                continue
            normalized.append({"role": role, "content": content})
        return "\n\n".join(system_parts), normalized

    def _merge_system_prompts(self, *parts: str) -> str:
        non_empty = [part.strip() for part in parts if part and part.strip()]
        return "\n\n".join(non_empty)

    def _extract_text(self, payload: Mapping[str, Any]) -> str | None:
        content = payload.get("content")
        if not isinstance(content, list):
            return None
        parts: list[str] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if not parts:
            return None
        return "".join(parts).strip()
