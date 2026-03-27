"""Settings page stub."""

from __future__ import annotations

from PySide6 import QtWidgets

from . import SimplePage, create_card


class SettingsPage(SimplePage):
    """Page for general preferences and data directory settings."""

    def __init__(self) -> None:
        super().__init__(
            "Settings",
            "Adjust privacy, storage, and general application preferences.",
        )

        privacy_card = QtWidgets.QGroupBox("Privacy", self)
        privacy_layout = QtWidgets.QVBoxLayout(privacy_card)
        privacy_layout.addWidget(
            QtWidgets.QCheckBox("Show manual approval prompts", privacy_card)
        )
        privacy_layout.addWidget(
            QtWidgets.QCheckBox("Mask provider secrets in the UI", privacy_card)
        )
        privacy_layout.addWidget(
            QtWidgets.QCheckBox("Include URLs in enrichment requests", privacy_card)
        )

        storage_card = QtWidgets.QGroupBox("Storage", self)
        storage_layout = QtWidgets.QFormLayout(storage_card)
        data_dir = QtWidgets.QLineEdit(storage_card)
        data_dir.setPlaceholderText("Select local data directory")
        storage_layout.addRow("Data directory", data_dir)
        storage_layout.addRow("Keyring", QtWidgets.QLabel("OS credential store", storage_card))

        info = create_card(
            "General",
            [
                "This page will eventually collect app-wide preferences and operational settings.",
                "Phase 5 keeps the layout lightweight but functional.",
            ],
        )

        self.content_layout.addWidget(privacy_card)
        self.content_layout.addWidget(storage_card)
        self.content_layout.addWidget(info)
