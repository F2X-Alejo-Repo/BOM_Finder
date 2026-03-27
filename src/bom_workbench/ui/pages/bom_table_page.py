"""BOM table page stub."""

from __future__ import annotations

from PySide6 import QtWidgets

from . import SimplePage, create_card


class BomTablePage(SimplePage):
    """Page for the canonical BOM table and enrichment summary."""

    def __init__(self) -> None:
        super().__init__(
            "BOM Table",
            "Review imported rows, inspect status, and trigger enrichment jobs.",
        )

        summary = create_card(
            "Summary",
            [
                "Rows: 142",
                "Enriched: 89",
                "Warnings: 8",
                "Alternates: 34",
            ],
        )

        table = QtWidgets.QTableWidget(3, 4, self)
        table.setHorizontalHeaderLabels(["Designator", "Comment", "Footprint", "State"])
        table.setItem(0, 0, QtWidgets.QTableWidgetItem("R1-R4"))
        table.setItem(0, 1, QtWidgets.QTableWidgetItem("100K"))
        table.setItem(0, 2, QtWidgets.QTableWidgetItem("0402"))
        table.setItem(0, 3, QtWidgets.QTableWidgetItem("Done"))
        table.setItem(1, 0, QtWidgets.QTableWidgetItem("C1, C2"))
        table.setItem(1, 1, QtWidgets.QTableWidgetItem("100nF"))
        table.setItem(1, 2, QtWidgets.QTableWidgetItem("0402"))
        table.setItem(1, 3, QtWidgets.QTableWidgetItem("Warn"))
        table.setItem(2, 0, QtWidgets.QTableWidgetItem("U1"))
        table.setItem(2, 1, QtWidgets.QTableWidgetItem("STM32F4"))
        table.setItem(2, 2, QtWidgets.QTableWidgetItem("LQFP-64"))
        table.setItem(2, 3, QtWidgets.QTableWidgetItem("Pending"))
        table.horizontalHeader().setStretchLastSection(True)

        actions = create_card(
            "Actions",
            [
                "Search, filter, and enrich rows from the active BOM view.",
                "Selection changes are forwarded to the inspector panel.",
            ],
        )
        action_row = QtWidgets.QHBoxLayout()
        action_row.addWidget(QtWidgets.QPushButton("Enrich Selected", self))
        action_row.addWidget(QtWidgets.QPushButton("Enrich All", self))
        action_row.addStretch(1)

        self.content_layout.addWidget(summary)
        self.content_layout.addLayout(action_row)
        self.content_layout.addWidget(table)
        self.content_layout.addWidget(actions)
