"""Jobs page widgets for live async job activity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from PySide6 import QtCore, QtWidgets

from . import SimplePage, create_card


class JobsPage(SimplePage):
    """Page for async job activity and logs."""

    pause_all_requested = QtCore.Signal()
    resume_all_requested = QtCore.Signal()
    cancel_all_requested = QtCore.Signal()
    retry_failed_requested = QtCore.Signal()
    clear_requested = QtCore.Signal()

    def __init__(self) -> None:
        super().__init__(
            "Jobs and Activity",
            "Track enrichment, export, and background job progress from one place.",
        )

        self._jobs_by_id: dict[int, dict[str, Any]] = {}

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(8)
        self.pause_all_button = QtWidgets.QPushButton("Pause All", self)
        self.resume_all_button = QtWidgets.QPushButton("Resume All", self)
        self.cancel_all_button = QtWidgets.QPushButton("Cancel All", self)
        self.retry_failed_button = QtWidgets.QPushButton("Retry Failed", self)
        self.clear_button = QtWidgets.QPushButton("Clear", self)
        action_row.addWidget(self.pause_all_button)
        action_row.addWidget(self.resume_all_button)
        action_row.addWidget(self.cancel_all_button)
        action_row.addWidget(self.retry_failed_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)

        self.jobs_table = QtWidgets.QTableWidget(0, 7, self)
        self.jobs_table.setHorizontalHeaderLabels(
            ["Job ID", "Type", "Status", "Rows", "Done", "Provider", "Duration"]
        )
        self.jobs_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.jobs_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.jobs_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.jobs_table.verticalHeader().setVisible(False)
        self.jobs_table.horizontalHeader().setStretchLastSection(True)
        self.jobs_table.itemSelectionChanged.connect(self._refresh_selected_details)

        details = create_card(
            "Selected Job Details",
            [
                "Progress, retries, and recent failures are displayed here.",
                "Select a job row to inspect metadata.",
            ],
        )
        self.details_text = QtWidgets.QPlainTextEdit(self)
        self.details_text.setReadOnly(True)
        self.details_text.setPlainText("No job selected.")

        self.pause_all_button.clicked.connect(self.pause_all_requested.emit)
        self.resume_all_button.clicked.connect(self.resume_all_requested.emit)
        self.cancel_all_button.clicked.connect(self.cancel_all_requested.emit)
        self.retry_failed_button.clicked.connect(self.retry_failed_requested.emit)
        self.clear_button.clicked.connect(self._handle_clear_clicked)

        self.content_layout.addLayout(action_row)
        self.content_layout.addWidget(self.jobs_table)
        self.content_layout.addWidget(details)
        self.content_layout.addWidget(self.details_text)

    def clear_jobs(self) -> None:
        """Clear all job rows and details."""
        self._jobs_by_id.clear()
        self.jobs_table.setRowCount(0)
        self.details_text.setPlainText("No job selected.")

    def set_jobs(self, jobs: Sequence[Mapping[str, Any] | Any]) -> None:
        """Replace table contents with the provided jobs."""
        self.clear_jobs()
        for job in jobs:
            self.upsert_job(job)

    def upsert_job(self, job: Mapping[str, Any] | Any) -> None:
        """Insert or update a single job row."""
        payload = self._coerce_job(job)
        job_id = int(payload.get("id", 0) or 0)
        if job_id <= 0:
            return

        self._jobs_by_id[job_id] = payload
        row_index = self._find_row_by_job_id(job_id)
        if row_index < 0:
            row_index = self.jobs_table.rowCount()
            self.jobs_table.insertRow(row_index)

        self._set_row(row_index, payload)
        self._refresh_selected_details()

    def _handle_clear_clicked(self) -> None:
        self.clear_requested.emit()
        self.clear_jobs()

    def _refresh_selected_details(self) -> None:
        selected = self.jobs_table.selectedItems()
        if not selected:
            self.details_text.setPlainText("No job selected.")
            return
        job_id = selected[0].data(QtCore.Qt.ItemDataRole.UserRole)
        if not isinstance(job_id, int):
            self.details_text.setPlainText("No job selected.")
            return
        payload = self._jobs_by_id.get(job_id)
        if not payload:
            self.details_text.setPlainText("No job details available.")
            return
        self.details_text.setPlainText(self._format_job_details(payload))

    def _find_row_by_job_id(self, job_id: int) -> int:
        for row_index in range(self.jobs_table.rowCount()):
            item = self.jobs_table.item(row_index, 0)
            if item is None:
                continue
            if item.data(QtCore.Qt.ItemDataRole.UserRole) == job_id:
                return row_index
        return -1

    def _set_row(self, row_index: int, payload: Mapping[str, Any]) -> None:
        job_id = int(payload.get("id", 0) or 0)
        job_label = f"J-{job_id:04d}"
        total_rows = int(payload.get("total_rows", 0) or 0)
        completed_rows = int(payload.get("completed_rows", 0) or 0)
        failed_rows = int(payload.get("failed_rows", 0) or 0)
        values = [
            job_label,
            str(payload.get("job_type", "") or "-"),
            str(payload.get("state", "") or "-"),
            str(total_rows),
            f"{completed_rows}/{total_rows} (failed: {failed_rows})",
            str(payload.get("provider_name", "") or "-"),
            self._duration_text(payload),
        ]
        for column_index, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            if column_index == 0:
                item.setData(QtCore.Qt.ItemDataRole.UserRole, job_id)
            self.jobs_table.setItem(row_index, column_index, item)

    def _duration_text(self, payload: Mapping[str, Any]) -> str:
        duration = payload.get("duration_seconds")
        if isinstance(duration, (int, float)) and duration >= 0:
            return f"{duration:.1f}s"

        started = self._parse_datetime(payload.get("started_at"))
        finished = self._parse_datetime(payload.get("finished_at"))
        if started is not None and finished is not None:
            seconds = max((finished - started).total_seconds(), 0.0)
            return f"{seconds:.1f}s"
        return "-"

    def _format_job_details(self, payload: Mapping[str, Any]) -> str:
        keys = [
            "id",
            "job_type",
            "state",
            "project_id",
            "target_row_ids",
            "total_rows",
            "completed_rows",
            "failed_rows",
            "provider_name",
            "model_name",
            "error_message",
            "retry_count",
            "started_at",
            "finished_at",
            "duration_seconds",
        ]
        lines: list[str] = []
        for key in keys:
            value = payload.get(key)
            if value in (None, ""):
                continue
            lines.append(f"{key}: {value}")
        return "\n".join(lines) if lines else "No job details available."

    def _coerce_job(self, job: Mapping[str, Any] | Any) -> dict[str, Any]:
        if isinstance(job, Mapping):
            return dict(job)
        if hasattr(job, "model_dump"):
            dumped = job.model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        if hasattr(job, "__dict__"):
            return {key: value for key, value in vars(job).items() if not key.startswith("_")}
        return {}

    def _parse_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
