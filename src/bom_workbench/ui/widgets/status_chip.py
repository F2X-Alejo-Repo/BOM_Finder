"""Compact status indicator widget."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QFrame, QHBoxLayout


class StatusChip(QFrame):
    """A small status pill with text and state styling."""

    _STATE_STYLES = {
        "neutral": "background:#eef2f7;color:#334155;border:1px solid #cbd5e1;",
        "success": "background:#ecfdf5;color:#166534;border:1px solid #86efac;",
        "warning": "background:#fffbeb;color:#92400e;border:1px solid #fcd34d;",
        "error": "background:#fef2f2;color:#991b1b;border:1px solid #fca5a5;",
        "info": "background:#eff6ff;color:#1d4ed8;border:1px solid #93c5fd;",
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
        self.setProperty("state", state)
        style = self._STATE_STYLES.get(state, self._STATE_STYLES["neutral"])
        self.setStyleSheet(
            "QFrame#statusChip {"
            "border-radius: 999px;"
            "font-weight: 600;"
            f"{style}"
            "}"
        )
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_text(self, text: str) -> None:
        self.set_status(text, self.property("state") or "neutral")

    def set_state(self, state: str) -> None:
        self.set_status(self._label.text(), state)
