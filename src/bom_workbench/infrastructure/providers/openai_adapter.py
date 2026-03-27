"""OpenAI provider adapter."""

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
    response_usage_from_openai,
    safe_connection_result,
    safe_provider_response,
)

OPENAI_BASE_URL = "https://api.openai.com"
OPENAI_MODELS_PATH = "/v1/models"
OPENAI_CHAT_PATH = "/v1/chat/completions"


class OpenAIProviderAdapter:
    """Adapter for OpenAI-compatible chat and model APIs."""

    def __init__(self, base_url: str = OPENAI_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    def get_name(self) -> str:
        return "openai"

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_model_discovery=True,
            supports_reasoning_control=True,
            supports_structured_output=True,
            supports_tool_use=True,
            supports_batch=False,
            supports_streaming=True,
            supports_temperature=True,
            reasoning_control_name="reasoning_effort",
            reasoning_levels=["low", "medium", "high"],
        )

    async def test_connection(self, api_key: str) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(api_key),
                timeout=build_timeout(10.0),
            ) as client:
                response = await client.get(OPENAI_MODELS_PATH)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else 0
            return safe_connection_result(
                provider=self.get_name(),
                success=False,
                message=f"OpenAI connection failed with HTTP {status_code}.",
                latency_ms=now_ms(start),
                details={"status_code": status_code},
            )
        except httpx.RequestError as exc:
            return safe_connection_result(
                provider=self.get_name(),
                success=False,
                message=f"OpenAI connection failed: {type(exc).__name__}.",
                latency_ms=now_ms(start),
                details={"error_type": type(exc).__name__},
            )

        return safe_connection_result(
            provider=self.get_name(),
            success=True,
            message="OpenAI connection successful.",
            latency_ms=now_ms(start),
        )

    async def discover_models(self, api_key: str) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(api_key),
                timeout=build_timeout(10.0),
            ) as client:
                response = await client.get(OPENAI_MODELS_PATH)
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
        request_messages = self._compose_messages(messages, config.system_prompt)
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": request_messages,
            "max_tokens": config.max_tokens,
        }
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        if config.reasoning_effort:
            payload["reasoning_effort"] = config.reasoning_effort
        if config.response_format:
            payload["response_format"] = self._response_format(config.response_format)

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(config.api_key),
                timeout=build_timeout(config.timeout_seconds),
            ) as client:
                response = await client.post(OPENAI_CHAT_PATH, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else 0
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=f"OpenAI chat failed with HTTP {status_code}.",
                raw_response={"status_code": status_code},
            )
        except httpx.RequestError as exc:
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=f"OpenAI chat failed: {type(exc).__name__}.",
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
                error_message="OpenAI response did not include assistant content.",
                raw_response=payload,
            )

        return safe_provider_response(
            content=content,
            model=config.model,
            provider=self.get_name(),
            latency_ms=now_ms(start),
            usage=response_usage_from_openai(payload),
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
        system_prompt = self._merge_system_prompts(
            config.system_prompt,
            "Return only valid JSON that matches this schema:\n" + schema_text,
        )
        request_messages = self._compose_messages(messages, system_prompt)
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": request_messages,
            "max_tokens": config.max_tokens,
            "response_format": {"type": "json_object"},
        }
        if config.temperature is not None:
            payload["temperature"] = config.temperature
        if config.reasoning_effort:
            payload["reasoning_effort"] = config.reasoning_effort

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(config.api_key),
                timeout=build_timeout(config.timeout_seconds),
            ) as client:
                response = await client.post(OPENAI_CHAT_PATH, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response else 0
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=f"OpenAI structured chat failed with HTTP {status_code}.",
                raw_response={"status_code": status_code},
            )
        except httpx.RequestError as exc:
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=f"OpenAI structured chat failed: {type(exc).__name__}.",
                raw_response={"error_type": type(exc).__name__},
            )

        payload = response.json()
        text = self._extract_text(payload)
        if text is None:
            return safe_provider_response(
                content="",
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message="OpenAI response did not include structured content.",
                raw_response=payload,
            )

        try:
            parsed = response_schema.model_validate_json(text)
        except Exception as exc:
            return safe_provider_response(
                content=text,
                model=config.model,
                provider=self.get_name(),
                latency_ms=now_ms(start),
                success=False,
                error_message=(
                    "OpenAI structured response validation failed: "
                    f"{type(exc).__name__}."
                ),
                raw_response=payload,
            )

        return safe_provider_response(
            content=parsed.model_dump_json(),
            model=config.model,
            provider=self.get_name(),
            latency_ms=now_ms(start),
            usage=response_usage_from_openai(payload),
            raw_response=payload,
        )

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _compose_messages(
        self,
        messages: Sequence[Mapping[str, str]],
        system_prompt: str,
    ) -> list[dict[str, str]]:
        system_from_messages, normalized = self._split_messages(messages)
        merged_system = self._merge_system_prompts(system_prompt, system_from_messages)
        if merged_system:
            return [{"role": "system", "content": merged_system}, *normalized]
        return normalized

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

    def _response_format(self, response_format: str) -> dict[str, str]:
        normalized = response_format.strip().lower()
        if normalized in {"json", "json_object"}:
            return {"type": "json_object"}
        return {"type": "json_object"}

    def _extract_text(self, payload: Mapping[str, Any]) -> str | None:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            return None
        message = first_choice.get("message")
        if not isinstance(message, Mapping):
            return None
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        return None
