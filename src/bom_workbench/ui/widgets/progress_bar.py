"""Progress display widget."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QProgressBar, QHBoxLayout, QVBoxLayout, QWidget


class ProgressBar(QWidget):
    """A labeled progress widget with convenience setters."""

    def __init__(
        self,
        label: str = "",
        value: int = 0,
        maximum: int = 100,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._label = QLabel(label, self)
        self._progress = QProgressBar(self)
        self._progress.setRange(0, maximum)
        self._progress.setValue(value)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self._label)
        top.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self._progress)

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def set_range(self, minimum: int, maximum: int) -> None:
        self._progress.setRange(minimum, maximum)

    def set_value(self, value: int) -> None:
        self._progress.setValue(value)

    def set_text(self, text: str) -> None:
        self._progress.setFormat(text)

    def set_status(self, text: str, busy: bool = False) -> None:
        self.set_label(text)
        self.set_busy(busy)

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._progress.setRange(0, 0)
            return
        self._progress.setRange(0, 100)
