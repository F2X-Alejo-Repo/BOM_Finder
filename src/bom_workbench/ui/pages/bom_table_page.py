"""BOM table page wiring for canonical BOM rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from . import SimplePage, create_card


class BomTableModel(QAbstractTableModel):
    """Qt table model for BomRow-like dictionaries."""

    _columns: list[tuple[str, str]] = [
        ("Designator", "designator"),
        ("Qty", "quantity"),
        ("Comment", "comment"),
        ("Footprint", "footprint"),
        ("LCSC #", "lcsc_part_number"),
        ("Manufacturer", "manufacturer"),
        ("MPN", "mpn"),
        ("Lifecycle", "lifecycle_status"),
        ("State", "row_state"),
    ]

    def __init__(
        self,
        rows: Sequence[Mapping[str, Any] | Any] | None = None,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self.set_rows(rows or [])

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        column_name = self._columns[index.column()][1]
        value = row.get(column_name, "")

        if role == Qt.ItemDataRole.DisplayRole:
            return self._format_value(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if column_name in {"quantity", "lcsc_part_number", "lifecycle_status"}:
                return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
            return int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._format_tooltip(row)
        if role == Qt.ItemDataRole.UserRole:
            return dict(row)
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._columns):
                return self._columns[section][0]
            return None
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def set_rows(self, rows: Sequence[Mapping[str, Any] | Any]) -> None:
        """Replace the model contents with BomRow-like payloads."""
        self.beginResetModel()
        self._rows = [self._coerce_row(row) for row in rows]
        self.endResetModel()

    def row_at(self, row_index: int) -> dict[str, Any] | None:
        if 0 <= row_index < len(self._rows):
            return dict(self._rows[row_index])
        return None

    def _coerce_row(self, row: Mapping[str, Any] | Any) -> dict[str, Any]:
        if isinstance(row, Mapping):
            return dict(row)
        if hasattr(row, "model_dump"):
            dumped = row.model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        if hasattr(row, "__dict__"):
            return {
                key: value
                for key, value in vars(row).items()
                if not key.startswith("_")
            }
        return {"value": row}

    def _format_value(self, value: Any) -> str:
        if value is None or value == "":
            return "-"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)

    def _format_tooltip(self, row: Mapping[str, Any]) -> str:
        parts = []
        for label, field in self._columns:
            value = row.get(field, "")
            if value in ("", None):
                continue
            parts.append(f"{label}: {value}")
        return "\n".join(parts)


class BomTablePage(SimplePage):
    """Page for the canonical BOM table and enrichment summary."""

    row_selected = Signal(dict)

    def __init__(self) -> None:
        super().__init__(
            "BOM Table",
            "Review imported rows, inspect status, and trigger enrichment jobs.",
        )

        summary = create_card(
            "Overview",
            [
                "Use the table to inspect normalized BOM rows.",
                "Selecting a row emits the selected BomRow-like payload.",
            ],
        )

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.enrich_selected_button = QPushButton("Enrich Selected", self)
        self.enrich_all_button = QPushButton("Enrich All", self)
        action_row.addWidget(self.enrich_selected_button)
        action_row.addWidget(self.enrich_all_button)
        action_row.addStretch(1)

        self.table_model = BomTableModel(parent=self)
        self.table_view = QTableView(self)
        self.table_view.setObjectName("BomTableView")
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(False)
        self.table_view.verticalHeader().setVisible(False)
        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table_view.selectionModel().currentRowChanged.connect(
            self._handle_current_row_changed
        )

        self.empty_state = QLabel(
            "Load BOM rows to populate the table.", self
        )
        self.empty_state.setObjectName("BomTableEmptyState")
        self.empty_state.setWordWrap(True)

        self.content_layout.addWidget(summary)
        self.content_layout.addLayout(action_row)
        self.content_layout.addWidget(self.table_view)
        self.content_layout.addWidget(self.empty_state)

    def set_rows(self, rows: Sequence[Mapping[str, Any] | Any]) -> None:
        """Replace the visible rows in the table model."""
        self.table_model.set_rows(rows)
        has_rows = self.table_model.rowCount() > 0
        self.empty_state.setVisible(not has_rows)
        if not has_rows:
            self.row_selected.emit({})

    def _handle_current_row_changed(
        self, current: QModelIndex, previous: QModelIndex
    ) -> None:
        del previous
        if not current.isValid():
            self.row_selected.emit({})
            return
        row = self.table_model.row_at(current.row())
        if row is not None:
            self.row_selected.emit(row)
