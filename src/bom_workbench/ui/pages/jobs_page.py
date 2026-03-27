"""Jobs page stub."""

from __future__ import annotations

from PySide6 import QtWidgets

from . import SimplePage, create_card


class JobsPage(SimplePage):
    """Page for async job activity and logs."""

    def __init__(self) -> None:
        super().__init__(
            "Jobs and Activity",
            "Track enrichment, export, and background job progress from one place.",
        )

        action_row = QtWidgets.QHBoxLayout()
        for label in ["Pause All", "Resume All", "Cancel All", "Retry Failed", "Clear"]:
            action_row.addWidget(QtWidgets.QPushButton(label, self))
        action_row.addStretch(1)

        jobs_table = QtWidgets.QTableWidget(3, 7, self)
        jobs_table.setHorizontalHeaderLabels(
            ["Job ID", "Type", "Status", "Rows", "Done", "Provider", "Duration"]
        )
        sample_rows = [
            ["J-042", "Enrich", "Running", "142", "89/142", "Claude", "2m 14s"],
            ["J-041", "Enrich", "Done", "50", "50/50", "GPT-4o", "1m 02s"],
            ["J-040", "Export", "Done", "1", "1/1", "-", "3s"],
        ]
        for row_index, values in enumerate(sample_rows):
            for column_index, value in enumerate(values):
                jobs_table.setItem(row_index, column_index, QtWidgets.QTableWidgetItem(value))
        jobs_table.horizontalHeader().setStretchLastSection(True)

        details = create_card(
            "Selected Job Details",
            [
                "Progress, retries, and recent failures will be surfaced here.",
                "This panel is intentionally stubbed for Phase 5.",
            ],
        )
        details_text = QtWidgets.QPlainTextEdit(self)
        details_text.setReadOnly(True)
        details_text.setPlainText(
            "Job details will be populated once the job manager is wired in."
        )

        self.content_layout.addLayout(action_row)
        self.content_layout.addWidget(jobs_table)
        self.content_layout.addWidget(details)
        self.content_layout.addWidget(details_text)
