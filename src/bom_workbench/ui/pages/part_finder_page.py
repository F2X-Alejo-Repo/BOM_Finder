"""Part finder page for replacement search and candidate review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt

from . import SimplePage, create_card


class _BaseTableModel(QtCore.QAbstractTableModel):
    def __init__(
        self,
        columns: Sequence[tuple[str, str]],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[dict[str, Any]] = []

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns)

    def data(
        self,
        index: QtCore.QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        field = self._columns[index.column()][1]
        value = row.get(field, "")
        if role == Qt.ItemDataRole.DisplayRole:
            return self._format_value(value)
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
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._columns):
            return self._columns[section][0]
        if orientation == Qt.Orientation.Vertical:
            return str(section + 1)
        return None

    def flags(self, index: QtCore.QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def set_rows(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = [dict(row) for row in rows]
        self.endResetModel()

    def row_at(self, row_index: int) -> dict[str, Any] | None:
        if 0 <= row_index < len(self._rows):
            return dict(self._rows[row_index])
        return None

    def _format_value(self, value: Any) -> str:
        if value in (None, ""):
            return "-"
        return str(value)

    def _format_tooltip(self, row: Mapping[str, Any]) -> str:
        parts = []
        for label, field in self._columns:
            value = row.get(field, "")
            if value in ("", None):
                continue
            parts.append(f"{label}: {value}")
        return "\n".join(parts)


class _CandidateTableModel(_BaseTableModel):
    _columns: list[tuple[str, str]] = [
        ("Targets", "targets"),
        ("Candidate", "candidate"),
        ("MPN", "mpn"),
        ("Footprint", "footprint"),
        ("Value", "value"),
        ("Manufacturer", "manufacturer"),
        ("Stock", "stock"),
        ("Score", "score"),
    ]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(self._columns, parent)


class _TargetTableModel(_BaseTableModel):
    _columns: list[tuple[str, str]] = [
        ("Designator", "designator"),
        ("MPN", "mpn"),
        ("Footprint", "footprint"),
        ("Qty", "quantity"),
        ("Stock", "stock"),
        ("Reason", "reason"),
    ]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(self._columns, parent)


class PartFinderPage(SimplePage):
    """Page for replacement search and candidate review."""

    search_from_selected_requested = QtCore.Signal()
    search_requested = QtCore.Signal(dict)
    bulk_search_requested = QtCore.Signal(dict)
    candidate_selected = QtCore.Signal(dict)
    apply_candidate_requested = QtCore.Signal(dict)

    def __init__(self) -> None:
        super().__init__(
            "Part Finder",
            "Search for replacements by part number, footprint, or electrical value.",
        )

        self._context_row: dict[str, Any] | None = None
        self._candidates: list[dict[str, Any]] = []
        self._bulk_targets: list[dict[str, Any]] = []
        self._searching = False
        self._applying = False

        context_card = create_card(
            "Context",
            [
                "Use the selected BOM row to seed search criteria.",
                "Bulk mode lets you review replacement candidates for selected or shortage rows.",
            ],
        )
        self.context_summary = QtWidgets.QLabel("No BOM row selected.", self)
        self.context_summary.setWordWrap(True)

        self.mode_tabs = QtWidgets.QTabWidget(self)
        self.single_tab = QtWidgets.QWidget(self.mode_tabs)
        self.bulk_tab = QtWidgets.QWidget(self.mode_tabs)
        self.mode_tabs.addTab(self.single_tab, "Single Row")
        self.mode_tabs.addTab(self.bulk_tab, "Bulk Review")

        self._build_single_row_tab()
        self._build_bulk_tab()

        filters_card = QtWidgets.QGroupBox("Filters", self)
        filters_layout = QtWidgets.QHBoxLayout(filters_card)
        filters_layout.setContentsMargins(12, 12, 12, 12)
        filters_layout.setSpacing(10)
        self.active_only_check = QtWidgets.QCheckBox("Active only", filters_card)
        self.in_stock_check = QtWidgets.QCheckBox("In stock", filters_card)
        self.lcsc_available_check = QtWidgets.QCheckBox("LCSC available", filters_card)
        filters_layout.addWidget(self.active_only_check)
        filters_layout.addWidget(self.in_stock_check)
        filters_layout.addWidget(self.lcsc_available_check)
        filters_layout.addStretch(1)

        candidates_group = QtWidgets.QGroupBox("Replacement Candidates", self)
        candidates_layout = QtWidgets.QVBoxLayout(candidates_group)
        self.candidate_model = _CandidateTableModel(self)
        self.candidate_view = QtWidgets.QTableView(self)
        self.candidate_view.setModel(self.candidate_model)
        self.candidate_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.candidate_view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.candidate_view.setAlternatingRowColors(True)
        self.candidate_view.setSortingEnabled(False)
        self.candidate_view.verticalHeader().setVisible(False)
        self.candidate_view.horizontalHeader().setStretchLastSection(True)
        candidates_layout.addWidget(self.candidate_view)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(10)
        self.apply_selected_button = QtWidgets.QPushButton(
            "Apply Selected Replacement", self
        )
        action_row.addWidget(self.apply_selected_button)
        action_row.addStretch(1)

        self.status_label = QtWidgets.QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("PartFinderStatus")

        self.content_layout.addWidget(context_card)
        self.content_layout.addWidget(self.context_summary)
        self.content_layout.addWidget(self.mode_tabs)
        self.content_layout.addWidget(filters_card)
        self.content_layout.addWidget(candidates_group)
        self.content_layout.addLayout(action_row)
        self.content_layout.addWidget(self.status_label)

        self.search_from_selected_button.clicked.connect(
            lambda _checked=False: self.search_from_selected_requested.emit()
        )
        self.search_button.clicked.connect(self._emit_search_requested)
        self.bulk_search_button.clicked.connect(self._emit_bulk_search_requested)
        self.apply_selected_button.clicked.connect(self._emit_apply_selected)
        self.candidate_view.selectionModel().currentRowChanged.connect(
            self._handle_current_row_changed
        )

    def _build_single_row_tab(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.single_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        search_card = QtWidgets.QGroupBox("Search Criteria", self.single_tab)
        search_layout = QtWidgets.QFormLayout(search_card)
        search_layout.setFieldGrowthPolicy(
            QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.part_number_edit = QtWidgets.QLineEdit(search_card)
        self.footprint_edit = QtWidgets.QLineEdit(search_card)
        self.value_edit = QtWidgets.QLineEdit(search_card)
        self.manufacturer_edit = QtWidgets.QLineEdit(search_card)

        self.part_number_edit.setPlaceholderText("MPN or LCSC part number")
        self.footprint_edit.setPlaceholderText("0402, LQFP-64, etc.")
        self.value_edit.setPlaceholderText("100nF, 10k, etc.")
        self.manufacturer_edit.setPlaceholderText("Optional manufacturer name")

        search_layout.addRow("Part # / MPN", self.part_number_edit)
        search_layout.addRow("Footprint", self.footprint_edit)
        search_layout.addRow("Value", self.value_edit)
        search_layout.addRow("Manufacturer", self.manufacturer_edit)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setSpacing(10)
        self.search_from_selected_button = QtWidgets.QPushButton(
            "Search from Selected BOM Row", self.single_tab
        )
        self.search_button = QtWidgets.QPushButton("Search", self.single_tab)
        action_row.addWidget(self.search_from_selected_button)
        action_row.addWidget(self.search_button)
        action_row.addStretch(1)

        layout.addWidget(search_card)
        layout.addLayout(action_row)

    def _build_bulk_tab(self) -> None:
        layout = QtWidgets.QVBoxLayout(self.bulk_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        bulk_scope_card = QtWidgets.QGroupBox("Bulk Scope", self.bulk_tab)
        scope_layout = QtWidgets.QHBoxLayout(bulk_scope_card)
        scope_layout.setContentsMargins(12, 12, 12, 12)
        scope_layout.setSpacing(10)

        self.bulk_scope_combo = QtWidgets.QComboBox(bulk_scope_card)
        self.bulk_scope_combo.addItem("Selected BOM rows", "selected_rows")
        self.bulk_scope_combo.addItem("No availability / qty 0", "no_availability")
        self.bulk_scope_combo.addItem("Insufficient stock", "insufficient_stock")
        self.bulk_scope_combo.addItem("Lifecycle risk", "lifecycle_risk")
        self.bulk_search_button = QtWidgets.QPushButton("Find Suggestions", bulk_scope_card)
        scope_layout.addWidget(self.bulk_scope_combo, 1)
        scope_layout.addWidget(self.bulk_search_button)

        self.bulk_summary = QtWidgets.QLabel(
            "Bulk review uses the current BOM selection or shortage scope.", self.bulk_tab
        )
        self.bulk_summary.setWordWrap(True)

        targets_group = QtWidgets.QGroupBox("Target Rows", self.bulk_tab)
        targets_layout = QtWidgets.QVBoxLayout(targets_group)
        self.target_model = _TargetTableModel(self.bulk_tab)
        self.target_view = QtWidgets.QTableView(self.bulk_tab)
        self.target_view.setModel(self.target_model)
        self.target_view.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.target_view.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.target_view.setAlternatingRowColors(True)
        self.target_view.setSortingEnabled(False)
        self.target_view.verticalHeader().setVisible(False)
        self.target_view.horizontalHeader().setStretchLastSection(True)
        targets_layout.addWidget(self.target_view)

        layout.addWidget(bulk_scope_card)
        layout.addWidget(self.bulk_summary)
        layout.addWidget(targets_group)

    def set_candidates(self, candidates: Sequence[Mapping[str, Any]]) -> None:
        self._candidates = [dict(candidate) for candidate in candidates]
        self.candidate_model.set_rows(self._candidates)
        if self.candidate_model.rowCount() == 0:
            self.candidate_view.clearSelection()

    def clear_candidates(self) -> None:
        self.set_candidates([])

    def set_context_row(self, row_payload: Mapping[str, Any] | None) -> None:
        self._context_row = dict(row_payload) if row_payload is not None else None
        if not self._context_row:
            self.context_summary.setText("No BOM row selected.")
            return

        summary_bits = []
        for label, field in (
            ("Designator", "designator"),
            ("MPN", "mpn"),
            ("Footprint", "footprint"),
            ("Value", "value"),
            ("Manufacturer", "manufacturer"),
        ):
            value = self._context_row.get(field, "")
            if value not in ("", None):
                summary_bits.append(f"{label}: {value}")
        self.context_summary.setText("Selected row - " + "; ".join(summary_bits))

    def set_bulk_targets(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        scope_label: str = "",
    ) -> None:
        self._bulk_targets = [dict(row) for row in rows]
        self.target_model.set_rows(self._bulk_targets)
        count = len(self._bulk_targets)
        label = scope_label or self.bulk_scope_combo.currentText()
        if count == 0:
            self.bulk_summary.setText(f"No target rows found for {label.lower()}.")
            return
        self.bulk_summary.setText(f"{label}: {count} target row(s) ready for review.")

    def clear_bulk_targets(self) -> None:
        self.set_bulk_targets([])

    def current_mode(self) -> str:
        if self.mode_tabs.currentWidget() is self.bulk_tab:
            return "bulk"
        return "single"

    def current_bulk_scope(self) -> str:
        return str(self.bulk_scope_combo.currentData() or "selected_rows")

    def set_status_message(self, text: str) -> None:
        self.status_label.setText(text.strip())

    def current_filters(self) -> dict[str, bool]:
        return {
            "active_only": self.active_only_check.isChecked(),
            "in_stock": self.in_stock_check.isChecked(),
            "lcsc_available": self.lcsc_available_check.isChecked(),
        }

    def set_busy_state(self, *, searching: bool = False, applying: bool = False) -> None:
        self._searching = searching
        self._applying = applying
        busy = searching or applying
        self.search_from_selected_button.setEnabled(not busy)
        self.search_button.setEnabled(not busy)
        self.bulk_search_button.setEnabled(not busy)
        self.apply_selected_button.setEnabled(not busy)
        self.part_number_edit.setEnabled(not busy)
        self.footprint_edit.setEnabled(not busy)
        self.value_edit.setEnabled(not busy)
        self.manufacturer_edit.setEnabled(not busy)
        self.bulk_scope_combo.setEnabled(not busy)
        self.active_only_check.setEnabled(not busy)
        self.in_stock_check.setEnabled(not busy)
        self.lcsc_available_check.setEnabled(not busy)
        self.candidate_view.setEnabled(not busy)
        self.target_view.setEnabled(not busy)
        self.mode_tabs.setEnabled(not busy)

    def is_busy(self) -> bool:
        return self._searching or self._applying

    def _emit_search_requested(self) -> None:
        criteria = {
            "part_number": self.part_number_edit.text().strip(),
            "footprint": self.footprint_edit.text().strip(),
            "value": self.value_edit.text().strip(),
            "manufacturer": self.manufacturer_edit.text().strip(),
            "filters": self.current_filters(),
            "context_row": dict(self._context_row) if self._context_row else None,
        }
        self.search_requested.emit(criteria)

    def _emit_bulk_search_requested(self) -> None:
        self.bulk_search_requested.emit(
            {
                "scope": self.current_bulk_scope(),
                "filters": self.current_filters(),
            }
        )

    def _emit_apply_selected(self) -> None:
        candidate = self._selected_candidate()
        if candidate is not None:
            self.apply_candidate_requested.emit(candidate)

    def _selected_candidate(self) -> dict[str, Any] | None:
        index = self.candidate_view.currentIndex()
        if not index.isValid():
            return None
        return self.candidate_model.row_at(index.row())

    def _handle_current_row_changed(
        self,
        current: QtCore.QModelIndex,
        previous: QtCore.QModelIndex,
    ) -> None:
        del previous
        if not current.isValid():
            return
        candidate = self.candidate_model.row_at(current.row())
        if candidate is not None:
            self.candidate_selected.emit(candidate)
