"""Provider configuration page for LLM connections."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6 import QtCore, QtWidgets

from . import SimplePage, create_card


@dataclass(slots=True)
class ProviderCapabilities:
    """Capability flags that drive which controls are visible."""

    show_reasoning_controls: bool = False
    show_connection_test: bool = True
    show_model_refresh: bool = True
    reasoning_label: str = "Reasoning"
    reasoning_help_text: str = ""


@dataclass(slots=True)
class _ProviderCard:
    """Widget bundle for one provider card."""

    provider: str
    group: QtWidgets.QGroupBox
    enabled: QtWidgets.QCheckBox
    connection_status_value: QtWidgets.QLabel
    api_key: QtWidgets.QLineEdit
    model: QtWidgets.QComboBox
    reasoning_group: QtWidgets.QGroupBox
    reasoning_mode: QtWidgets.QComboBox
    test_button: QtWidgets.QPushButton
    refresh_button: QtWidgets.QPushButton
    runtime_defaults: dict[str, Any] = field(default_factory=dict)
    selected_model_hint: str = ""
    _model_placeholder: str = field(default="No models loaded yet")


class ProvidersPage(SimplePage):
    """Page for LLM provider configuration."""

    test_connection_clicked = QtCore.Signal(str, str)
    refresh_models_clicked = QtCore.Signal(str, str)
    save_settings_clicked = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__(
            "LLM Providers",
            "Configure provider access, model selection, and runtime options.",
        )

        self._provider_cards: dict[str, _ProviderCard] = {}

        self._provider_cards["openai"] = self._create_provider_card(
            provider="openai",
            title="OpenAI",
            status_text="Not checked",
        )
        self._provider_cards["anthropic"] = self._create_provider_card(
            provider="anthropic",
            title="Anthropic",
            status_text="Not checked",
        )

        self.apply_provider_capabilities(
            "openai",
            ProviderCapabilities(
                show_reasoning_controls=True,
                reasoning_label="Reasoning effort",
                reasoning_help_text=(
                    "Use provider-supported reasoning controls when available."
                ),
            ),
        )
        self.apply_provider_capabilities(
            "anthropic",
            ProviderCapabilities(
                show_reasoning_controls=True,
                reasoning_label="Thinking",
                reasoning_help_text=(
                    "Expose Anthropic thinking controls when supported."
                ),
            ),
        )

        info = create_card(
            "Runtime Controls",
            [
                "Model discovery, timeouts, retries, and concurrency controls "
                "will be wired here.",
                "Provider-specific controls stay dynamic and capability-driven.",
            ],
        )

        self.save_button = QtWidgets.QPushButton("Save Settings", self)
        self.save_button.setObjectName("saveProvidersButton")
        self.save_button.clicked.connect(self._emit_save_settings)

        self.content_layout.addWidget(self._provider_cards["openai"].group)
        self.content_layout.addWidget(self._provider_cards["anthropic"].group)
        self.content_layout.addWidget(info)
        self.content_layout.addWidget(self.save_button)

    def set_provider_models(
        self,
        provider: str,
        models: Sequence[str],
        selected_model: str | None = None,
    ) -> None:
        """Replace the model list for a provider."""
        card = self._get_provider_card(provider)
        combo = card.model

        selected_hint = self._clean_text(card.selected_model_hint)
        if selected_hint == card._model_placeholder:
            selected_hint = ""
        current_selection = (
            self._clean_text(selected_model)
            or selected_hint
            or combo.currentText().strip()
        )
        if current_selection == card._model_placeholder:
            current_selection = ""
        combo.blockSignals(True)
        combo.clear()
        model_names = [self._clean_text(model) for model in models if self._clean_text(model)]
        if current_selection and current_selection not in model_names:
            model_names = [current_selection, *model_names]
        if model_names:
            combo.addItems(model_names)
            if current_selection and current_selection in model_names:
                combo.setCurrentText(current_selection)
            else:
                combo.setCurrentIndex(0)
        else:
            combo.addItem(current_selection or card._model_placeholder)
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
        combo.blockSignals(False)
        if model_names:
            combo.setEnabled(True)
        card.selected_model_hint = current_selection
        card.runtime_defaults["cached_models"] = list(model_names)
        if current_selection:
            card.runtime_defaults["selected_model"] = current_selection

    def set_connection_status_text(self, provider: str, text: str) -> None:
        """Update the status text shown on a provider card."""
        card = self._get_provider_card(provider)
        card.connection_status_value.setText(text.strip() or "Not checked")

    def set_provider_api_key(self, provider: str, api_key: str) -> None:
        """Apply an API key value to a provider card."""

        card = self._get_provider_card(provider)
        card.api_key.setText(api_key.strip())

    def set_provider_runtime_settings(
        self,
        provider: str,
        *,
        enabled: bool,
        selected_model: str = "",
        reasoning_mode: str = "",
    ) -> None:
        """Apply persisted runtime settings to a provider card."""

        card = self._get_provider_card(provider)
        card.enabled.setChecked(enabled)
        card.runtime_defaults["enabled"] = enabled

        normalized_model = selected_model.strip()
        if normalized_model:
            card.selected_model_hint = normalized_model
            if card.model.findText(normalized_model) < 0:
                existing_models = self._visible_model_names(card)
                if normalized_model not in existing_models:
                    existing_models = [normalized_model, *existing_models]
                self.set_provider_models(
                    provider,
                    existing_models or [normalized_model],
                    selected_model=normalized_model,
                )
            else:
                card.model.setCurrentText(normalized_model)
            card.runtime_defaults["selected_model"] = normalized_model
        elif card.selected_model_hint:
            card.runtime_defaults["selected_model"] = card.selected_model_hint

        normalized_reasoning = reasoning_mode.strip().title()
        if normalized_reasoning:
            index = card.reasoning_mode.findText(normalized_reasoning)
            if index >= 0:
                card.reasoning_mode.setCurrentIndex(index)
            card.runtime_defaults["reasoning_mode"] = normalized_reasoning

    def hydrate_provider_settings(
        self,
        provider: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Hydrate a provider card from persisted runtime settings."""

        normalized = self._normalize_runtime_settings(settings, provider=provider)
        card = self._get_provider_card(provider)
        card.runtime_defaults = normalized
        cached_models = list(normalized["cached_models"])
        selected_model = str(normalized["selected_model"])
        if cached_models or selected_model:
            self.set_provider_models(
                provider,
                cached_models or [selected_model],
                selected_model=selected_model,
            )
        self.set_provider_runtime_settings(
            provider,
            enabled=bool(normalized["enabled"]),
            selected_model=selected_model,
            reasoning_mode=str(normalized["reasoning_mode"]),
        )

    def hydrate_provider_settings_bulk(
        self,
        settings_by_provider: Mapping[str, Mapping[str, Any]],
    ) -> None:
        """Hydrate multiple provider cards from persisted runtime settings."""

        for provider, settings in settings_by_provider.items():
            if provider in self._provider_cards:
                self.hydrate_provider_settings(provider, settings)

    def apply_provider_capabilities(
        self,
        provider: str,
        capabilities: ProviderCapabilities | Mapping[str, Any],
    ) -> None:
        """Show or hide provider-specific controls based on capability flags."""
        card = self._get_provider_card(provider)
        normalized = self._normalize_capabilities(capabilities)

        card.reasoning_group.setVisible(normalized.show_reasoning_controls)
        if normalized.show_reasoning_controls:
            card.reasoning_group.setTitle(normalized.reasoning_label)
            card.reasoning_group.setToolTip(normalized.reasoning_help_text)
        else:
            card.reasoning_group.setToolTip("")

        card.test_button.setVisible(normalized.show_connection_test)
        card.refresh_button.setVisible(normalized.show_model_refresh)

    def provider_settings(self) -> dict[str, dict[str, Any]]:
        """Return the current provider configuration payload."""
        return {
            provider: self._card_payload(card)
            for provider, card in self._provider_cards.items()
        }

    def _create_provider_card(
        self,
        provider: str,
        title: str,
        status_text: str,
    ) -> _ProviderCard:
        group = QtWidgets.QGroupBox(title, self)
        group.setObjectName(f"{provider}ProviderCard")
        group_layout = QtWidgets.QVBoxLayout(group)
        group_layout.setContentsMargins(16, 16, 16, 16)
        group_layout.setSpacing(12)

        header = QtWidgets.QFrame(group)
        header.setObjectName(f"{provider}ProviderHeader")
        header_layout = QtWidgets.QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        provider_hint = QtWidgets.QLabel(
            "Configure credentials, pick a model, and inspect provider health.",
            header,
        )
        provider_hint.setWordWrap(True)
        header_layout.addWidget(provider_hint)

        status_row = QtWidgets.QHBoxLayout()
        status_label = QtWidgets.QLabel("Connection status", header)
        connection_status_value = QtWidgets.QLabel(status_text, header)
        connection_status_value.setObjectName(f"{provider}ConnectionStatus")
        connection_status_value.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status_row.addWidget(status_label)
        status_row.addWidget(connection_status_value, 1)
        header_layout.addLayout(status_row)
        group_layout.addWidget(header)

        form = QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)

        enabled = QtWidgets.QCheckBox("Enabled", group)
        enabled.setChecked(True)

        api_key = QtWidgets.QLineEdit(group)
        api_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        api_key.setPlaceholderText("Paste API key")

        model = QtWidgets.QComboBox(group)
        model.setObjectName(f"{provider}ModelCombo")
        model.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContentsOnFirstShow
        )
        model.addItem("No models loaded yet")
        model.setCurrentIndex(0)
        model.setEnabled(False)

        reasoning_group = QtWidgets.QGroupBox("Reasoning", group)
        reasoning_group.setObjectName(f"{provider}ReasoningGroup")
        reasoning_layout = QtWidgets.QFormLayout(reasoning_group)
        reasoning_layout.setContentsMargins(12, 12, 12, 12)
        reasoning_layout.setSpacing(8)

        reasoning_mode = QtWidgets.QComboBox(reasoning_group)
        reasoning_mode.addItems(["Auto", "Low", "Medium", "High"])
        reasoning_layout.addRow("Mode", reasoning_mode)

        reasoning_note = QtWidgets.QLabel(
            "Capability-driven controls appear here when a provider supports them.",
            reasoning_group,
        )
        reasoning_note.setWordWrap(True)
        reasoning_note.setObjectName(f"{provider}ReasoningNote")
        reasoning_layout.addRow(reasoning_note)

        form.addRow("Enabled", enabled)
        form.addRow("API Key", api_key)
        form.addRow("Model", model)
        form.addRow(reasoning_group)
        group_layout.addLayout(form)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(10)
        test_button = QtWidgets.QPushButton("Test Connection", group)
        refresh_button = QtWidgets.QPushButton("Refresh Models", group)
        test_button.clicked.connect(
            lambda _checked=False, provider=provider: self._emit_provider_action(
                provider, "test"
            )
        )
        refresh_button.clicked.connect(
            lambda _checked=False, provider=provider: self._emit_provider_action(
                provider, "refresh"
            )
        )
        action_row.addWidget(test_button)
        action_row.addWidget(refresh_button)
        action_row.addStretch(1)
        group_layout.addLayout(action_row)

        card = _ProviderCard(
            provider=provider,
            group=group,
            enabled=enabled,
            connection_status_value=connection_status_value,
            api_key=api_key,
            model=model,
            reasoning_group=reasoning_group,
            reasoning_mode=reasoning_mode,
            test_button=test_button,
            refresh_button=refresh_button,
        )
        return card

    def _emit_provider_action(self, provider: str, action: str) -> None:
        card = self._get_provider_card(provider)
        api_key = card.api_key.text().strip()
        if action == "test":
            self.test_connection_clicked.emit(provider, api_key)
        elif action == "refresh":
            self.refresh_models_clicked.emit(provider, api_key)

    def _emit_save_settings(self) -> None:
        self.save_settings_clicked.emit(self.provider_settings())

    def _card_payload(self, card: _ProviderCard) -> dict[str, Any]:
        payload = dict(card.runtime_defaults)
        cached_models = self._normalize_models(payload.get("cached_models"))
        if not cached_models:
            cached_models = self._visible_model_names(card)

        selected_model = card.model.currentText().strip()
        if selected_model == card._model_placeholder:
            selected_model = ""
        reasoning_mode = card.reasoning_mode.currentText().strip() or "Auto"
        timeout_seconds = self._normalize_int(payload.get("timeout_seconds"), default=60)
        max_retries = self._normalize_int(payload.get("max_retries"), default=3)
        max_concurrent = self._normalize_int(payload.get("max_concurrent"), default=5)
        temperature = self._normalize_temperature(payload.get("temperature"))
        reasoning_effort = self._normalize_reasoning_effort(
            payload.get("reasoning_effort", reasoning_mode)
        )

        payload.update(
            {
                "provider": card.provider,
                "enabled": card.enabled.isChecked(),
                "api_key": card.api_key.text().strip(),
                "selected_model": selected_model,
                "reasoning_mode": reasoning_mode,
                "reasoning_effort": reasoning_effort,
                "connection_status": card.connection_status_value.text().strip(),
                "cached_models": cached_models,
                "timeout_seconds": timeout_seconds,
                "max_retries": max_retries,
                "max_concurrent": max_concurrent,
                "temperature": temperature,
                "auth_method": self._clean_text(payload.get("auth_method", "api_key"))
                or "api_key",
                "privacy_level": self._clean_text(payload.get("privacy_level", "full"))
                or "full",
                "manual_approval": bool(payload.get("manual_approval", False)),
                "models_cached_at": self._normalize_datetime_text(
                    payload.get("models_cached_at")
                ),
                "extra_config": self._normalize_extra_config(payload.get("extra_config")),
                "runtime_defaults": dict(card.runtime_defaults),
            }
        )
        return payload

    def _visible_model_names(self, card: _ProviderCard) -> list[str]:
        names: list[str] = []
        for index in range(card.model.count()):
            text = card.model.itemText(index).strip()
            if text and text != card._model_placeholder and text not in names:
                names.append(text)
        return names

    def _normalize_models(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return []
            if cleaned.startswith("["):
                try:
                    parsed = json.loads(cleaned)
                except json.JSONDecodeError:
                    parsed = []
                if isinstance(parsed, list):
                    return [self._clean_text(item) for item in parsed if self._clean_text(item)]
            return [segment.strip() for segment in cleaned.split(",") if segment.strip()]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [self._clean_text(item) for item in value if self._clean_text(item)]
        text = self._clean_text(value)
        return [text] if text else []

    def _normalize_int(self, value: object, *, default: int) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        text = self._clean_text(value)
        if text.isdigit():
            return int(text)
        return default

    def _normalize_temperature(self, value: object) -> float | None:
        if value in {None, ""}:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = self._clean_text(value)
        try:
            return float(text)
        except ValueError:
            return None

    def _normalize_reasoning_mode(self, value: object) -> str:
        text = self._clean_text(value)
        if not text:
            return "Auto"
        lowered = text.casefold()
        if lowered in {"auto", "default"}:
            return "Auto"
        if lowered in {"low", "medium", "high"}:
            return lowered.title()
        return text

    def _normalize_reasoning_effort(self, value: object) -> str:
        text = self._clean_text(value)
        if not text:
            return ""
        lowered = text.casefold()
        if lowered in {"auto", "default"}:
            return ""
        if lowered in {"low", "medium", "high"}:
            return lowered
        return lowered

    def _normalize_datetime_text(self, value: object) -> str:
        return self._clean_text(value)

    def _normalize_extra_config(self, value: object) -> dict[str, Any] | str:
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ""
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return text
            if isinstance(parsed, Mapping):
                return dict(parsed)
            return text
        return {}

    def _normalize_runtime_settings(
        self,
        settings: Mapping[str, Any],
        *,
        provider: str,
    ) -> dict[str, Any]:
        provider_name = self._clean_text(settings.get("provider", provider)) or provider
        enabled = bool(settings.get("enabled", True))
        selected_model = self._clean_text(settings.get("selected_model", ""))
        reasoning_mode = self._normalize_reasoning_mode(settings.get("reasoning_mode", "Auto"))
        cached_models = self._normalize_models(settings.get("cached_models"))
        timeout_seconds = self._normalize_int(settings.get("timeout_seconds"), default=60)
        max_retries = self._normalize_int(settings.get("max_retries"), default=3)
        max_concurrent = self._normalize_int(settings.get("max_concurrent"), default=5)
        temperature = self._normalize_temperature(settings.get("temperature"))
        reasoning_effort = self._normalize_reasoning_effort(
            settings.get("reasoning_effort", reasoning_mode)
        )
        auth_method = self._clean_text(settings.get("auth_method", "api_key")) or "api_key"
        privacy_level = self._clean_text(settings.get("privacy_level", "full")) or "full"
        manual_approval = bool(settings.get("manual_approval", False))
        models_cached_at = self._normalize_datetime_text(settings.get("models_cached_at"))
        extra_config = self._normalize_extra_config(settings.get("extra_config"))

        return {
            "provider": provider_name,
            "enabled": enabled,
            "selected_model": selected_model,
            "reasoning_mode": reasoning_mode,
            "reasoning_effort": reasoning_effort,
            "cached_models": cached_models,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "max_concurrent": max_concurrent,
            "temperature": temperature,
            "auth_method": auth_method,
            "privacy_level": privacy_level,
            "manual_approval": manual_approval,
            "models_cached_at": models_cached_at,
            "extra_config": extra_config,
        }

    def _clean_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _get_provider_card(self, provider: str) -> _ProviderCard:
        try:
            return self._provider_cards[provider]
        except KeyError as exc:
            known = ", ".join(sorted(self._provider_cards))
            raise KeyError(
                f"Unknown provider '{provider}'. Known providers: {known}"
            ) from exc

    def _normalize_capabilities(
        self,
        capabilities: ProviderCapabilities | Mapping[str, Any],
    ) -> ProviderCapabilities:
        if isinstance(capabilities, ProviderCapabilities):
            return capabilities

        reasoning_label = capabilities.get("reasoning_label", "Reasoning")
        reasoning_help_text = capabilities.get("reasoning_help_text", "")
        return ProviderCapabilities(
            show_reasoning_controls=bool(
                capabilities.get("show_reasoning_controls", False)
            ),
            show_connection_test=bool(capabilities.get("show_connection_test", True)),
            show_model_refresh=bool(capabilities.get("show_model_refresh", True)),
            reasoning_label=str(reasoning_label),
            reasoning_help_text=str(reasoning_help_text),
        )
