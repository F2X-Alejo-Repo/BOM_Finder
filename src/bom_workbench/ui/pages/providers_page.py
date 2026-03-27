"""Provider configuration page stub."""

from __future__ import annotations

from PySide6 import QtWidgets

from . import SimplePage, create_card


class ProvidersPage(SimplePage):
    """Page for LLM provider configuration."""

    def __init__(self) -> None:
        super().__init__(
            "LLM Providers",
            "Configure provider access, model selection, and runtime options.",
        )

        openai_card = QtWidgets.QGroupBox("OpenAI", self)
        openai_layout = QtWidgets.QFormLayout(openai_card)
        openai_enabled = QtWidgets.QCheckBox("Enabled", openai_card)
        openai_key = QtWidgets.QLineEdit(openai_card)
        openai_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        openai_model = QtWidgets.QComboBox(openai_card)
        openai_model.addItems(["gpt-4o", "gpt-4.1", "gpt-5"])
        openai_layout.addRow("Status", openai_enabled)
        openai_layout.addRow("API Key", openai_key)
        openai_layout.addRow("Model", openai_model)
        openai_actions = QtWidgets.QHBoxLayout()
        openai_actions.addWidget(QtWidgets.QPushButton("Test Connection", openai_card))
        openai_actions.addWidget(QtWidgets.QPushButton("Refresh Models", openai_card))
        openai_actions.addStretch(1)
        openai_layout.addRow(openai_actions)

        anthropic_card = QtWidgets.QGroupBox("Anthropic", self)
        anthropic_layout = QtWidgets.QFormLayout(anthropic_card)
        anthropic_enabled = QtWidgets.QCheckBox("Enabled", anthropic_card)
        anthropic_key = QtWidgets.QLineEdit(anthropic_card)
        anthropic_key.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        anthropic_model = QtWidgets.QComboBox(anthropic_card)
        anthropic_model.addItems(["claude-sonnet-4", "claude-opus-4", "claude-haiku-4"])
        anthropic_layout.addRow("Status", anthropic_enabled)
        anthropic_layout.addRow("API Key", anthropic_key)
        anthropic_layout.addRow("Model", anthropic_model)
        anthropic_layout.addRow("Thinking", QtWidgets.QComboBox(anthropic_card))
        anthropic_actions = QtWidgets.QHBoxLayout()
        anthropic_actions.addWidget(QtWidgets.QPushButton("Test Connection", anthropic_card))
        anthropic_actions.addWidget(QtWidgets.QPushButton("Refresh Models", anthropic_card))
        anthropic_actions.addStretch(1)
        anthropic_layout.addRow(anthropic_actions)

        info = create_card(
            "Runtime Controls",
            [
                "Model discovery, timeouts, retries, and concurrency controls will be wired here.",
                "Provider-specific controls should stay dynamic and capability-driven.",
            ],
        )

        self.content_layout.addWidget(openai_card)
        self.content_layout.addWidget(anthropic_card)
        self.content_layout.addWidget(info)
