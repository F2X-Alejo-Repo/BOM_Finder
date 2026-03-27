"""Export page stub."""

from __future__ import annotations

from PySide6 import QtWidgets

from . import SimplePage, create_card


class ExportPage(SimplePage):
    """Page for export target and report configuration."""

    def __init__(self) -> None:
        super().__init__(
            "Export",
            "Prepare procurement-ready Excel output and report options.",
        )

        target_card = QtWidgets.QGroupBox("Export Target", self)
        target_layout = QtWidgets.QVBoxLayout(target_card)
        current_view = QtWidgets.QRadioButton("Current filtered view", target_card)
        full_table = QtWidgets.QRadioButton("Full canonical table", target_card)
        final_bom = QtWidgets.QRadioButton("Final procurement BOM", target_card)
        final_bom.setChecked(True)
        target_layout.addWidget(current_view)
        target_layout.addWidget(full_table)
        target_layout.addWidget(final_bom)

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
        for label in [
            "Include metadata sheet",
            "Apply color coding",
            "Preserve hyperlinks",
        ]:
            checkbox = QtWidgets.QCheckBox(label, options_card)
            checkbox.setChecked(True)
            options_layout.addWidget(checkbox)

        export_button = QtWidgets.QPushButton("Export to File...", self)

        self.content_layout.addWidget(target_card)
        self.content_layout.addWidget(columns)
        self.content_layout.addWidget(options_card)
        self.content_layout.addWidget(export_button)
