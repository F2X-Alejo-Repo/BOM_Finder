"""Row inspector widget for selected BOM rows."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QFrame, QGroupBox, QLabel, QVBoxLayout


class RowInspector(QFrame):
    """Right-side row inspection panel."""

    _field_groups: list[tuple[str, list[tuple[str, str]]]] = [
        (
            "Part",
            [
                ("designator", "Designator"),
                ("quantity", "Quantity"),
                ("comment", "Comment"),
                ("footprint", "Footprint"),
                ("lcsc_part_number", "LCSC Part #"),
            ],
        ),
        (
            "Supply",
            [
                ("manufacturer", "Manufacturer"),
                ("mpn", "MPN"),
                ("stock_qty", "Stock Qty"),
                ("stock_status", "Stock Status"),
                ("lifecycle_status", "Lifecycle"),
                ("row_state", "State"),
            ],
        ),
        (
            "Source",
            [
                ("source_file", "Source File"),
                ("original_row_index", "Source Row"),
                ("source_confidence", "Source Confidence"),
            ],
        ),
    ]

    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rowInspector")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        title = QLabel("Row Inspector", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        self.subtitle = QLabel(
            "Select a BOM row to view its normalized fields.", self
        )
        self.subtitle.setWordWrap(True)
        self.subtitle.setProperty("muted", True)
        root.addWidget(self.subtitle)

        self._value_labels: dict[str, QLabel] = {}

        for group_title, fields in self._field_groups:
            group = QGroupBox(group_title, self)
            form = QFormLayout(group)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            for field_key, field_label in fields:
                value_label = QLabel("-", group)
                value_label.setWordWrap(True)
                value_label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                    | Qt.TextInteractionFlag.TextSelectableByKeyboard
                )
                self._value_labels[field_key] = value_label
                form.addRow(field_label, value_label)
            root.addWidget(group)

        root.addStretch(1)

    def set_row(self, row_data: Mapping[str, Any] | None) -> None:
        """Populate the inspector with BomRow-like dictionary values."""
        if not row_data:
            self.clear_row()
            return

        normalized = dict(row_data)
        self.subtitle.setText(self._build_subtitle(normalized))
        for field_key, label in self._value_labels.items():
            label.setText(self._format_value(normalized.get(field_key)))

    def clear_row(self) -> None:
        """Reset the displayed values."""
        self.subtitle.setText("Select a BOM row to view its normalized fields.")
        for label in self._value_labels.values():
            label.setText("-")

    def _build_subtitle(self, row_data: Mapping[str, Any]) -> str:
        designator = row_data.get("designator")
        comment = row_data.get("comment")
        source_file = row_data.get("source_file")
        parts = [part for part in [designator, comment, source_file] if part]
        if not parts:
            return "Selected BOM row"
        return " - ".join(str(part) for part in parts[:3])

    def _format_value(self, value: Any) -> str:
        if value is None or value == "":
            return "-"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        if isinstance(value, float):
            return f"{value:.3f}".rstrip("0").rstrip(".")
        return str(value)
