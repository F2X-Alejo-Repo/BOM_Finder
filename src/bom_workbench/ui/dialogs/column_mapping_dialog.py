"""Dialog for reviewing detected import column mappings."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6 import QtCore, QtWidgets


class ColumnMappingDialog(QtWidgets.QDialog):
    """Show detected mappings, warnings, and unmapped source columns."""

    def __init__(
        self,
        detected_mappings: Mapping[str, str] | None = None,
        unmapped_columns: list[str] | None = None,
        warnings: list[str] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ColumnMappingDialog")
        self.setWindowTitle("Column Mapping")
        self.setModal(True)
        self.resize(720, 520)
        self.setMinimumSize(680, 480)
        self.setSizeGripEnabled(True)

        self._selected_mappings = dict(detected_mappings or {})

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        title = QtWidgets.QLabel("Review detected column mappings", self)
        title.setStyleSheet("font-size: 16px; font-weight: 700;")
        root.addWidget(title)

        self.mapping_table = QtWidgets.QTableWidget(self)
        self.mapping_table.setColumnCount(2)
        self.mapping_table.setHorizontalHeaderLabels(["Source column", "Mapped field"])
        self.mapping_table.setHorizontalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.mapping_table.setVerticalScrollMode(
            QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.mapping_table.setShowGrid(False)
        self.mapping_table.verticalHeader().setVisible(False)
        self.mapping_table.verticalHeader().setDefaultSectionSize(36)
        header = self.mapping_table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setMinimumSectionSize(96)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.mapping_table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.AllEditTriggers
        )
        self.mapping_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        content_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, self)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setHandleWidth(8)
        content_splitter.addWidget(self.mapping_table)

        unmapped_group = QtWidgets.QGroupBox("Unmapped columns", self)
        unmapped_layout = QtWidgets.QVBoxLayout(unmapped_group)
        self.unmapped_list = QtWidgets.QListWidget(unmapped_group)
        unmapped_layout.addWidget(self.unmapped_list)

        warnings_group = QtWidgets.QGroupBox("Warnings", self)
        warnings_layout = QtWidgets.QVBoxLayout(warnings_group)
        self.warning_list = QtWidgets.QListWidget(warnings_group)
        warnings_layout.addWidget(self.warning_list)

        details_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        details_splitter.setChildrenCollapsible(False)
        details_splitter.setHandleWidth(8)
        details_splitter.addWidget(unmapped_group)
        details_splitter.addWidget(warnings_group)
        details_splitter.setStretchFactor(0, 1)
        details_splitter.setStretchFactor(1, 1)
        content_splitter.addWidget(details_splitter)
        content_splitter.setStretchFactor(0, 3)
        content_splitter.setStretchFactor(1, 2)
        root.addWidget(content_splitter, 1)

        button_box = QtWidgets.QDialogButtonBox(self)
        button_box.setStandardButtons(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root.addWidget(button_box)

        self.set_mappings(detected_mappings or {})
        self.set_unmapped_columns(unmapped_columns or [])
        self.set_warnings(warnings or [])

    @property
    def selected_mappings(self) -> dict[str, str]:
        """Return the currently selected mapping entries."""
        return dict(self._selected_mappings)

    def set_mappings(self, mappings: Mapping[str, str]) -> None:
        """Replace the detected mapping list shown in the dialog."""
        self._selected_mappings = dict(mappings)
        self.mapping_table.setRowCount(len(self._selected_mappings))
        for row, (source_column, mapped_field) in enumerate(self._selected_mappings.items()):
            self.mapping_table.setItem(row, 0, QtWidgets.QTableWidgetItem(source_column))
            self.mapping_table.setItem(row, 1, QtWidgets.QTableWidgetItem(mapped_field))

    def set_unmapped_columns(self, columns: list[str]) -> None:
        """Replace the list of source columns that were not mapped."""
        self.unmapped_list.clear()
        self.unmapped_list.addItems(columns)

    def set_warnings(self, warnings: list[str]) -> None:
        """Replace the list of import warnings."""
        self.warning_list.clear()
        self.warning_list.addItems(warnings)

    def accept(self) -> None:
        """Capture the current selection before closing with accept."""
        selected: dict[str, str] = {}
        for row in range(self.mapping_table.rowCount()):
            source_item = self.mapping_table.item(row, 0)
            mapped_item = self.mapping_table.item(row, 1)
            if source_item is None or mapped_item is None:
                continue
            source_column = source_item.text().strip()
            mapped_field = mapped_item.text().strip()
            if source_column and mapped_field:
                selected[source_column] = mapped_field
        self._selected_mappings = selected
        super().accept()
