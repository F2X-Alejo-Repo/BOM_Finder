"""Export page for procurement-ready workbook export."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6 import QtCore, QtWidgets

from . import SimplePage, create_card


class ExportPage(SimplePage):
    """Page for export target and report configuration."""

    export_requested = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__(
            "Export",
            "Prepare procurement-ready Excel output and report options.",
        )

        target_card = QtWidgets.QGroupBox("Export Target", self)
        target_layout = QtWidgets.QVBoxLayout(target_card)
        self.target_group = QtWidgets.QButtonGroup(self)
        self.procurement_target = QtWidgets.QRadioButton(
            "Final procurement BOM", target_card
        )
        self.full_table_target = QtWidgets.QRadioButton(
            "Full canonical table", target_card
        )
        self.current_view_target = QtWidgets.QRadioButton(
            "Current filtered view", target_card
        )
        self.procurement_target.setChecked(True)
        self.target_group.addButton(self.procurement_target)
        self.target_group.addButton(self.full_table_target)
        self.target_group.addButton(self.current_view_target)
        target_layout.addWidget(self.procurement_target)
        target_layout.addWidget(self.full_table_target)
        target_layout.addWidget(self.current_view_target)

        columns = create_card(
            "Preview Columns",
            [
                "Designator",
                "Comment",
                "Footprint",
                "LCSC LINK",
                "LCSC PART #",
            ],
        )

        options_card = QtWidgets.QGroupBox("Options", self)
        options_layout = QtWidgets.QVBoxLayout(options_card)
        self.include_metadata_check = QtWidgets.QCheckBox(
            "Include metadata sheet", options_card
        )
        self.apply_color_coding_check = QtWidgets.QCheckBox(
            "Apply color coding", options_card
        )
        self.preserve_hyperlinks_check = QtWidgets.QCheckBox(
            "Preserve hyperlinks", options_card
        )
        self.sanitize_formulas_check = QtWidgets.QCheckBox(
            "Sanitize formulas", options_card
        )
        for checkbox in (
            self.include_metadata_check,
            self.apply_color_coding_check,
            self.preserve_hyperlinks_check,
            self.sanitize_formulas_check,
        ):
            checkbox.setChecked(True)
            options_layout.addWidget(checkbox)

        self.export_button = QtWidgets.QPushButton("Export to File...", self)
        self.export_button.clicked.connect(self._emit_export_requested)

        self.status_label = QtWidgets.QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("ExportStatus")
        self.last_result_label = QtWidgets.QLabel(
            "No export has been run yet.", self
        )
        self.last_result_label.setWordWrap(True)
        self.last_result_label.setObjectName("ExportResult")

        self.content_layout.addWidget(target_card)
        self.content_layout.addWidget(columns)
        self.content_layout.addWidget(options_card)
        self.content_layout.addWidget(self.export_button)
        self.content_layout.addWidget(self.status_label)
        self.content_layout.addWidget(self.last_result_label)

    def set_status_message(self, text: str) -> None:
        """Update the page status text."""

        self.status_label.setText(text.strip())

    def set_last_export_result(self, result: Mapping[str, Any] | None) -> None:
        """Update the summary text for the most recent export."""

        if result is None:
            self.last_result_label.setText("No export has been run yet.")
            return

        pieces: list[str] = []
        output_path = str(result.get("output_path", "")).strip()
        if output_path:
            pieces.append(f"Output: {output_path}")
        rows_exported = result.get("rows_exported")
        if rows_exported is not None:
            pieces.append(f"Rows exported: {rows_exported}")
        sheets_created = result.get("sheets_created")
        if isinstance(sheets_created, list) and sheets_created:
            pieces.append("Sheets: " + ", ".join(str(sheet) for sheet in sheets_created))
        warnings = result.get("warnings")
        if isinstance(warnings, list) and warnings:
            pieces.append(f"Warnings: {len(warnings)}")
        duration_seconds = result.get("duration_seconds")
        if duration_seconds is not None:
            pieces.append(f"Duration: {duration_seconds}")
        file_size_bytes = result.get("file_size_bytes")
        if file_size_bytes is not None:
            pieces.append(f"Size: {file_size_bytes} bytes")
        self.last_result_label.setText(" | ".join(pieces) if pieces else "Export completed.")

    def _emit_export_requested(self) -> None:
        payload = {
            "target": self._selected_target(),
            "options": {
                "include_metadata_sheet": self.include_metadata_check.isChecked(),
                "apply_color_coding": self.apply_color_coding_check.isChecked(),
                "preserve_hyperlinks": self.preserve_hyperlinks_check.isChecked(),
                "sanitize_formulas": self.sanitize_formulas_check.isChecked(),
            },
        }
        self.export_requested.emit(payload)

    def _selected_target(self) -> str:
        if self.full_table_target.isChecked():
            return "full_table"
        if self.current_view_target.isChecked():
            return "current_filtered_view"
        return "procurement_bom"
