"""Dialog for showing a completed import summary."""

from __future__ import annotations

from PySide6 import QtWidgets


class ImportReportDialog(QtWidgets.QDialog):
    """Display a compact summary of an import run."""

    def __init__(
        self,
        *,
        file_name: str,
        rows_imported: int,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        unmapped_columns: list[str] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ImportReportDialog")
        self.setWindowTitle("Import Report")
        self.setModal(True)
        self.resize(640, 480)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Import complete", self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        summary_group = QtWidgets.QGroupBox("Summary", self)
        summary_form = QtWidgets.QFormLayout(summary_group)
        summary_form.addRow("File", QtWidgets.QLabel(file_name, summary_group))
        summary_form.addRow(
            "Rows imported", QtWidgets.QLabel(str(rows_imported), summary_group)
        )
        summary_form.addRow(
            "Warnings", QtWidgets.QLabel(str(len(warnings or [])), summary_group)
        )
        summary_form.addRow(
            "Errors", QtWidgets.QLabel(str(len(errors or [])), summary_group)
        )
        summary_form.addRow(
            "Unmapped cols",
            QtWidgets.QLabel(str(len(unmapped_columns or [])), summary_group),
        )
        root.addWidget(summary_group)

        lists_layout = QtWidgets.QHBoxLayout()
        lists_layout.addWidget(self._build_list_group("Warnings", warnings or []))
        lists_layout.addWidget(self._build_list_group("Errors", errors or []))
        lists_layout.addWidget(
            self._build_list_group("Unmapped columns", unmapped_columns or [])
        )
        root.addLayout(lists_layout)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok, self
        )
        button_box.accepted.connect(self.accept)
        root.addWidget(button_box)

    def _build_list_group(
        self, title: str, items: list[str]
    ) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title, self)
        layout = QtWidgets.QVBoxLayout(group)
        list_widget = QtWidgets.QListWidget(group)
        list_widget.addItems(items)
        layout.addWidget(list_widget)
        return group
