"""Table model for canonical BOM rows."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore

from ...domain.entities import BomRow


class BomTableModel(QtCore.QAbstractTableModel):
    """QAbstractTableModel backed by a list of BomRow records."""

    HEADERS: tuple[str, ...] = (
        "Designator",
        "Comment",
        "Value",
        "Footprint",
        "Manufacturer",
        "MPN",
        "State",
    )

    def __init__(
        self,
        rows: Sequence[BomRow] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[BomRow] = list(rows or [])

    def rowCount(
        self, parent: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(
        self, parent: QtCore.QModelIndex = QtCore.QModelIndex()
    ) -> int:
        if parent.isValid():
            return 0
        return len(self.HEADERS)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.ItemDataRole.DisplayRole
    ) -> object | None:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role in (QtCore.Qt.ItemDataRole.DisplayRole, QtCore.Qt.ItemDataRole.EditRole):
            return self._value_for_column(row, index.column())
        return None

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.ItemDataRole.DisplayRole,
    ) -> object | None:
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == QtCore.Qt.Orientation.Horizontal and 0 <= section < len(self.HEADERS):
            return self.HEADERS[section]
        if orientation == QtCore.Qt.Orientation.Vertical:
            return section + 1
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlag:
        if not index.isValid():
            return QtCore.Qt.ItemFlag.NoItemFlags
        return (
            QtCore.Qt.ItemFlag.ItemIsSelectable
            | QtCore.Qt.ItemFlag.ItemIsEnabled
            | QtCore.Qt.ItemFlag.ItemNeverHasChildren
        )

    def set_rows(self, rows: Sequence[BomRow]) -> None:
        """Replace the full row set."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def update_row(self, row_index: int, row: BomRow) -> None:
        """Replace one row in place and notify attached views."""
        if not (0 <= row_index < len(self._rows)):
            raise IndexError(f"Row index out of range: {row_index}")
        self._rows[row_index] = row
        top_left = self.index(row_index, 0)
        bottom_right = self.index(row_index, self.columnCount() - 1)
        self.dataChanged.emit(top_left, bottom_right, [])

    def row_at(self, index: int) -> BomRow:
        """Return the row at a given model index."""
        if not (0 <= index < len(self._rows)):
            raise IndexError(f"Row index out of range: {index}")
        return self._rows[index]

    def rows(self) -> list[BomRow]:
        """Return a shallow copy of the current row list."""
        return list(self._rows)

    def _value_for_column(self, row: BomRow, column: int) -> object:
        if column == 0:
            return row.designator
        if column == 1:
            return row.comment
        if column == 2:
            return row.value_raw
        if column == 3:
            return row.footprint
        if column == 4:
            return row.manufacturer
        if column == 5:
            return row.mpn
        if column == 6:
            return row.row_state
        return ""
