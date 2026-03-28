"""Compact status indicator widget."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QFrame, QHBoxLayout


class StatusChip(QFrame):
    """A small status pill with text and state styling."""

    _STATE_STYLES = {
        "neutral": "neutral",
        "success": "success",
        "warning": "warning",
        "error": "error",
        "info": "info",
    }

    def __init__(self, text: str = "", state: str = "neutral", parent: Optional[QFrame] = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusChip")
        self._label = QLabel(text, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.addWidget(self._label)

        self.set_status(text, state)

    def set_status(self, text: str, state: str = "neutral") -> None:
        self._label.setText(text)
        self.setProperty("state", self._STATE_STYLES.get(state, "neutral"))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_text(self, text: str) -> None:
        self.set_status(text, self.property("state") or "neutral")

    def set_state(self, state: str) -> None:
        self.set_status(self._label.text(), state)
