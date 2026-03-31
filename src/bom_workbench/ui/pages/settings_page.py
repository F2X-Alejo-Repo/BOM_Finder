"""Settings page stub."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

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

        workspace_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        workspace_splitter.setChildrenCollapsible(False)
        workspace_splitter.addWidget(privacy_card)
        workspace_splitter.addWidget(storage_card)
        workspace_splitter.setStretchFactor(0, 1)
        workspace_splitter.setStretchFactor(1, 1)
        workspace_splitter.setSizes([420, 420])

        self.content_layout.addWidget(workspace_splitter)
        self.content_layout.addWidget(info)
