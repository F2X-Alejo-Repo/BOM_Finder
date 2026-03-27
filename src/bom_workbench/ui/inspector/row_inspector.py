"""Row inspector widget stub."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtWidgets


class RowInspector(QtWidgets.QFrame):
    """Right-side row inspection panel."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rowInspector")
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QtWidgets.QLabel("Row Inspector", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        self.summary_labels: dict[str, QtWidgets.QLabel] = {}

        summary_card = QtWidgets.QGroupBox("Current Row", self)
        summary_layout = QtWidgets.QFormLayout(summary_card)
        for key in ["Designator", "Comment", "Footprint", "LCSC"]:
            value_label = QtWidgets.QLabel("-", summary_card)
            self.summary_labels[key.lower()] = value_label
            summary_layout.addRow(key, value_label)

        sourcing_card = QtWidgets.QGroupBox("Sourcing", self)
        sourcing_layout = QtWidgets.QFormLayout(sourcing_card)
        for key in ["Stock", "Lifecycle", "EOL Risk", "Confidence"]:
            value_label = QtWidgets.QLabel("-", sourcing_card)
            self.summary_labels[key.lower().replace(" ", "_")] = value_label
            sourcing_layout.addRow(key, value_label)

        evidence_card = QtWidgets.QGroupBox("Evidence", self)
        evidence_layout = QtWidgets.QVBoxLayout(evidence_card)
        evidence_layout.addWidget(QtWidgets.QLabel("Evidence records: 0", evidence_card))
        evidence_layout.addWidget(QtWidgets.QPushButton("View Evidence", evidence_card))

        action_card = QtWidgets.QGroupBox("Actions", self)
        action_layout = QtWidgets.QVBoxLayout(action_card)
        for label in ["Enrich Row", "Find Replacement", "Export Row"]:
            action_layout.addWidget(QtWidgets.QPushButton(label, action_card))

        root.addWidget(summary_card)
        root.addWidget(sourcing_card)
        root.addWidget(evidence_card)
        root.addWidget(action_card)
        root.addStretch(1)

    def set_row(self, row_data: Mapping[str, Any]) -> None:
        """Populate the stub with simple display values."""
        for key, value in row_data.items():
            label = self.summary_labels.get(key)
            if label is not None:
                label.setText(str(value))

    def clear_row(self) -> None:
        """Reset the displayed values."""
        for label in self.summary_labels.values():
            label.setText("-")
