"""Search input widget."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLineEdit, QHBoxLayout, QWidget


class SearchBar(QWidget):
    """Line edit with a clean, reusable constructor."""

    def __init__(self, placeholder: str = "Search", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._line_edit = QLineEdit(self)
        self._line_edit.setPlaceholderText(placeholder)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._line_edit)

    def text(self) -> str:
        return self._line_edit.text()

    def set_text(self, text: str) -> None:
        self._line_edit.setText(text)

    def clear(self) -> None:
        self._line_edit.clear()

    def set_placeholder_text(self, text: str) -> None:
        self._line_edit.setPlaceholderText(text)

    @property
    def line_edit(self) -> QLineEdit:
        return self._line_edit
