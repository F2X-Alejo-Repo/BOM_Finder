"""Shared helpers for provider adapters."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel

from ...domain.ports import (
    ConnectionTestResult,
    ModelInfo,
    ProviderResponse,
)

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 60.0
DEFAULT_WRITE_TIMEOUT = 10.0
DEFAULT_POOL_TIMEOUT = 5.0

SAFE_ERROR_MESSAGE = "Provider request failed."


def build_timeout(read_timeout: float) -> httpx.Timeout:
    """Create an explicit timeout object for provider calls."""

    return httpx.Timeout(
        connect=DEFAULT_CONNECT_TIMEOUT,
        read=read_timeout,
        write=DEFAULT_WRITE_TIMEOUT,
        pool=DEFAULT_POOL_TIMEOUT,
    )


def sanitize_error_text(message: str) -> str:
    """Strip common secret-bearing patterns from diagnostic text."""

    if not message:
        return SAFE_ERROR_MESSAGE

    redacted = message
    for token in ("Bearer ", "bearer ", "sk-", "x-api-key", "api_key"):
        if token in redacted:
            redacted = redacted.replace(token, "[redacted]")

    return redacted


def now_ms(start: float) -> float:
    """Return elapsed milliseconds for a perf counter start value."""

    return round((time.perf_counter() - start) * 1000.0, 2)


def extract_system_prompt(
    messages: Sequence[Mapping[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    """Split system content from the rest of the chat payload."""

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


def response_usage_from_openai(payload: Mapping[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def response_usage_from_anthropic(payload: Mapping[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def safe_connection_result(
    *,
    provider: str,
    success: bool,
    message: str,
    latency_ms: float,
    details: dict[str, Any] | None = None,
) -> ConnectionTestResult:
    return ConnectionTestResult(
        success=success,
        message=sanitize_error_text(message),
        provider=provider,
        latency_ms=latency_ms,
        details=details or {},
    )


def safe_provider_response(
    *,
    content: str,
    model: str,
    provider: str,
    latency_ms: float,
    usage: dict[str, int] | None = None,
    raw_response: dict[str, Any] | None = None,
    success: bool = True,
    error_message: str = "",
) -> ProviderResponse:
    return ProviderResponse(
        content=content,
        model=model,
        provider=provider,
        usage=usage or {},
        raw_response=raw_response or {},
        latency_ms=latency_ms,
        success=success,
        error_message=sanitize_error_text(error_message),
    )


def model_from_payload(
    *,
    provider: str,
    payload: Mapping[str, Any],
) -> ModelInfo:
    created_at = payload.get("created")
    return ModelInfo(
        id=str(payload.get("id", "")),
        name=str(
            payload.get("display_name")
            or payload.get("name")
            or payload.get("id")
            or "",
        ),
        provider=provider,
        context_window=_coerce_context_window(payload),
        supports_vision=_coerce_bool(
            payload.get("supports_vision")
            or payload.get("vision")
            or payload.get("modalities")
        ),
        supports_tools=_coerce_bool(
            payload.get("supports_tools")
            or payload.get("tool_use")
            or payload.get("tools")
        ),
        created_at=_coerce_created_at(created_at),
    )


def _coerce_context_window(payload: Mapping[str, Any]) -> int | None:
    for key in ("context_window", "max_context_window", "max_tokens"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return bool(value)
    return bool(value)


def _coerce_created_at(value: Any) -> Any:
    if isinstance(value, (int, float)):
        from datetime import UTC, datetime

        return datetime.fromtimestamp(float(value), tz=UTC)
    return None


@dataclass(slots=True)
class StructuredPrompt:
    """Prompt scaffold for schema-guided JSON responses."""

    system: str
    user: str


def build_structured_prompt(
    response_schema: type[BaseModel],
    messages: Sequence[Mapping[str, str]],
) -> StructuredPrompt:
    """Construct a deterministic JSON-only prompt for structured output."""

    schema = json.dumps(response_schema.model_json_schema(), indent=2, sort_keys=True)
    system_prompt, normalized = extract_system_prompt(messages)
    system_parts = [
        "You are a strict JSON generator.",
        "Return only valid JSON that matches the provided schema.",
    ]
    if system_prompt:
        system_parts.append(system_prompt)

    user_lines = [
        "Schema:",
        schema,
        "",
        "Conversation:",
        json.dumps(normalized, indent=2, sort_keys=True),
    ]
    return StructuredPrompt(
        system="\n\n".join(system_parts),
        user="\n".join(user_lines),
    )
