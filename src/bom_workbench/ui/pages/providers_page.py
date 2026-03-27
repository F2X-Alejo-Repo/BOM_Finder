"""Provider configuration page for LLM connections."""

from __future__ import annotations

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

        current_selection = selected_model or combo.currentText().strip()
        combo.blockSignals(True)
        combo.clear()
        model_names = [model.strip() for model in models if model.strip()]
        if model_names:
            combo.addItems(model_names)
            if current_selection and current_selection in model_names:
                combo.setCurrentText(current_selection)
            else:
                combo.setCurrentIndex(0)
        else:
            combo.addItem(card._model_placeholder)
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
        combo.blockSignals(False)
        if model_names:
            combo.setEnabled(True)

    def set_connection_status_text(self, provider: str, text: str) -> None:
        """Update the status text shown on a provider card."""
        card = self._get_provider_card(provider)
        card.connection_status_value.setText(text.strip() or "Not checked")

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
        return {
            "provider": card.provider,
            "enabled": card.enabled.isChecked(),
            "api_key": card.api_key.text().strip(),
            "selected_model": card.model.currentText().strip(),
            "reasoning_mode": card.reasoning_mode.currentText().strip(),
            "connection_status": card.connection_status_value.text().strip(),
        }

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
