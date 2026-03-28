"""Provider runtime configuration persistence and hydration helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from ..domain.entities import ProviderConfig
from ..domain.ports import IProviderConfigRepository

__all__ = [
    "ProviderRuntimeConfigService",
    "ProviderRuntimeConfigSnapshot",
]


@dataclass(slots=True, frozen=True)
class ProviderRuntimeConfigSnapshot:
    """Normalized runtime settings for a single provider."""

    provider_name: str
    enabled: bool = False
    selected_model: str = ""
    cached_models: tuple[str, ...] = ()
    models_cached_at: datetime | None = None
    timeout_seconds: int = 60
    max_retries: int = 3
    max_concurrent: int = 5
    temperature: float | None = None
    reasoning_effort: str = ""
    privacy_level: str = "full"
    manual_approval: bool = False
    auth_method: str = "api_key"
    extra_config: dict[str, Any] = field(default_factory=dict)

    def to_page_payload(self) -> dict[str, Any]:
        """Render the snapshot into the provider page payload shape."""

        return {
            "provider": self.provider_name,
            "enabled": self.enabled,
            "selected_model": self.selected_model,
            "reasoning_mode": _effort_to_reasoning_mode(self.reasoning_effort),
            "reasoning_effort": self.reasoning_effort,
            "cached_models": list(self.cached_models),
            "models_cached_at": self.models_cached_at.isoformat() if self.models_cached_at else "",
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "max_concurrent": self.max_concurrent,
            "temperature": self.temperature,
            "auth_method": self.auth_method,
            "privacy_level": self.privacy_level,
            "manual_approval": self.manual_approval,
            "extra_config": dict(self.extra_config),
        }


class ProviderRuntimeConfigService:
    """Persist and hydrate provider runtime settings."""

    def __init__(self, repository: IProviderConfigRepository) -> None:
        self._repository = repository

    async def save_provider_settings(
        self,
        settings_by_provider: Mapping[str, Mapping[str, Any]],
    ) -> list[ProviderConfig]:
        """Persist provider settings from a page payload."""

        saved: list[ProviderConfig] = []
        for provider_name, payload in settings_by_provider.items():
            if not _normalize_provider_name(provider_name):
                continue
            existing = await self._repository.get_by_provider(provider_name)
            config = self._build_config(provider_name, payload, existing=existing)
            saved.append(await self._repository.save(config))
        return saved

    async def load_provider_settings(
        self,
        provider_names: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Load provider settings using the page payload shape."""

        snapshots = await self.list_provider_snapshots(provider_names)
        return {snapshot.provider_name: snapshot.to_page_payload() for snapshot in snapshots}

    async def get_provider_snapshot(
        self,
        provider_name: str,
    ) -> ProviderRuntimeConfigSnapshot | None:
        """Load one provider snapshot by name."""

        config = await self._repository.get_by_provider(provider_name)
        if config is None:
            return None
        return self._snapshot_from_config(config)

    async def list_provider_snapshots(
        self,
        provider_names: Sequence[str] | None = None,
    ) -> list[ProviderRuntimeConfigSnapshot]:
        """Load provider snapshots, optionally filtered to a subset of names."""

        configs = await self._repository.list_all()
        wanted = {_normalize_provider_name(name) for name in provider_names} if provider_names else None
        snapshots = [
            self._snapshot_from_config(config)
            for config in configs
            if wanted is None or config.provider_name in wanted
        ]
        return sorted(snapshots, key=lambda snapshot: snapshot.provider_name)

    def _build_config(
        self,
        provider_name: str,
        payload: Mapping[str, Any],
        *,
        existing: ProviderConfig | None = None,
    ) -> ProviderConfig:
        normalized_provider = _normalize_provider_name(provider_name)
        base = (existing or ProviderConfig(provider_name=normalized_provider)).model_dump(
            mode="python"
        )
        runtime_payload = payload.get("runtime_defaults")
        runtime_defaults = (
            runtime_payload if isinstance(runtime_payload, Mapping) else payload
        )
        has_runtime_defaults = bool(runtime_defaults)
        use_page_runtime_values = existing is None or has_runtime_defaults

        base["provider_name"] = normalized_provider
        if use_page_runtime_values:
            base["enabled"] = _coerce_bool(payload.get("enabled", base["enabled"]))

        selected_model = _clean_text(payload.get("selected_model", ""))
        if selected_model and (use_page_runtime_values or not _clean_text(base["selected_model"])):
            base["selected_model"] = selected_model

        if use_page_runtime_values:
            cached_models = _coerce_models(runtime_defaults.get("cached_models"))
            if cached_models:
                base["cached_models"] = _encode_json_list(cached_models)
                base["models_cached_at"] = _coerce_datetime(
                    runtime_defaults.get("models_cached_at"),
                    fallback=datetime.now(UTC),
                )

            timeout_seconds = _coerce_int(
                runtime_defaults.get("timeout_seconds"), base["timeout_seconds"]
            )
            max_retries = _coerce_int(runtime_defaults.get("max_retries"), base["max_retries"])
            max_concurrent = _coerce_int(
                runtime_defaults.get("max_concurrent"), base["max_concurrent"]
            )
            temperature = _coerce_temperature(
                runtime_defaults.get("temperature"), base["temperature"]
            )
            reasoning_effort = _normalize_reasoning_effort(
                runtime_defaults.get(
                    "reasoning_effort",
                    payload.get("reasoning_mode", base["reasoning_effort"]),
                )
            )
            privacy_level = _clean_text(runtime_defaults.get("privacy_level", base["privacy_level"]))
            auth_method = _clean_text(runtime_defaults.get("auth_method", base["auth_method"]))
            manual_approval = _coerce_bool(
                runtime_defaults.get("manual_approval", base["manual_approval"])
            )
            extra_config = _encode_extra_config(
                runtime_defaults.get("extra_config", base["extra_config"])
            )

            base.update(
                {
                    "timeout_seconds": timeout_seconds,
                    "max_retries": max_retries,
                    "max_concurrent": max_concurrent,
                    "temperature": temperature,
                    "reasoning_effort": reasoning_effort,
                    "privacy_level": privacy_level or "full",
                    "auth_method": auth_method or "api_key",
                    "manual_approval": manual_approval,
                    "extra_config": extra_config,
                }
            )
        return ProviderConfig(**base)

    def _snapshot_from_config(self, config: ProviderConfig) -> ProviderRuntimeConfigSnapshot:
        return ProviderRuntimeConfigSnapshot(
            provider_name=_normalize_provider_name(config.provider_name),
            enabled=bool(config.enabled),
            selected_model=_clean_text(config.selected_model),
            cached_models=tuple(_coerce_models(config.cached_models)),
            models_cached_at=config.models_cached_at,
            timeout_seconds=int(config.timeout_seconds or 60),
            max_retries=int(config.max_retries or 3),
            max_concurrent=int(config.max_concurrent or 5),
            temperature=config.temperature if config.temperature is not None else None,
            reasoning_effort=_normalize_reasoning_effort(config.reasoning_effort),
            privacy_level=_clean_text(config.privacy_level) or "full",
            manual_approval=bool(config.manual_approval),
            auth_method=_clean_text(config.auth_method) or "api_key",
            extra_config=_decode_extra_config(config.extra_config),
        )


def _normalize_provider_name(provider_name: object) -> str:
    return _clean_text(provider_name).lower()


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, int):
        return bool(value)
    text = _clean_text(value).casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = _clean_text(value)
    if text.isdigit():
        return int(text)
    return default


def _coerce_temperature(value: object, default: float | None) -> float | None:
    if value in {None, ""}:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = _clean_text(value)
    try:
        return float(text)
    except ValueError:
        return default


def _coerce_datetime(value: object, *, fallback: datetime | None = None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = _clean_text(value)
    if not text:
        return fallback
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _coerce_models(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                return [_clean_text(item) for item in parsed if _clean_text(item)]
        return [segment.strip() for segment in text.split(",") if segment.strip()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_clean_text(item) for item in value if _clean_text(item)]
    text = _clean_text(value)
    return [text] if text else []


def _encode_json_list(values: Sequence[str]) -> str:
    return json.dumps([_clean_text(value) for value in values if _clean_text(value)], ensure_ascii=True)


def _encode_extra_config(value: object) -> str:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        return text
    if isinstance(value, Mapping):
        return json.dumps(
            dict(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    if value in {None, ""}:
        return ""
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _decode_extra_config(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    text = _clean_text(value)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"value": text}
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {"value": parsed}


def _normalize_reasoning_effort(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    lowered = text.casefold()
    if lowered in {"auto", "default"}:
        return ""
    if lowered in {"low", "medium", "high"}:
        return lowered
    return lowered


def _effort_to_reasoning_mode(value: str) -> str:
    normalized = _normalize_reasoning_effort(value)
    if not normalized:
        return "Auto"
    return normalized.title()
