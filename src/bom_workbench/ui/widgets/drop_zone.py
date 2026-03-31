"""Drag-and-drop file intake widget."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout


class DropZone(QFrame):
    """Accepts dragged files and emits their local paths."""

    files_dropped = Signal(list)

    def __init__(self, label: str = "Drop files here", parent: Optional[QFrame] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self.setMinimumHeight(180)
        self._label = QLabel(label, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(self._label)

        self._set_active(False)

    def set_label(self, text: str) -> None:
        self._label.setText(text)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._extract_paths(event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_active(True)
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        del event
        self._set_active(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = self._extract_paths(event.mimeData().urls())
        self._set_active(False)
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    @staticmethod
    def _extract_paths(urls: Iterable) -> list[str]:
        paths: list[str] = []
        for url in urls:
            if not url.isLocalFile():
                continue
            path = str(Path(url.toLocalFile()))
            if path:
                paths.append(path)
        return paths
