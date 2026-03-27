"""Import page wiring for file intake."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..widgets import DropZone
from . import SimplePage, create_card


class ImportPage(SimplePage):
    """Page for BOM import entry points."""

    import_requested = Signal(list)

    def __init__(self) -> None:
        super().__init__(
            "BOM Import",
            "Drag CSV files here or use the file picker to start a new import.",
        )

        self._recent_imports: list[dict[str, Any]] = []

        intake_card = QFrame(self)
        intake_card.setObjectName("ImportIntakeCard")
        intake_card.setFrameShape(QFrame.Shape.StyledPanel)
        intake_layout = QVBoxLayout(intake_card)
        intake_layout.setContentsMargins(18, 18, 18, 18)
        intake_layout.setSpacing(12)

        self.drop_zone = DropZone(
            "Drop CSV files here or use the browse buttons",
            intake_card,
        )
        self.drop_zone.files_dropped.connect(self._handle_dropped_files)

        hint = QLabel(
            "Import one or more CSV files from disk. Folder browse collects CSV files "
            "from the selected directory.",
            intake_card,
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        self.browse_files_button = QPushButton("Browse Files", intake_card)
        self.browse_folder_button = QPushButton("Browse Folder", intake_card)
        self.browse_files_button.clicked.connect(self._browse_files)
        self.browse_folder_button.clicked.connect(self._browse_folder)
        button_row.addWidget(self.browse_files_button)
        button_row.addWidget(self.browse_folder_button)

        intake_layout.addWidget(self.drop_zone)
        intake_layout.addWidget(hint)
        intake_layout.addLayout(button_row)

        recent_card = create_card("Recent Imports", [])
        self.recent_imports_list = QListWidget(recent_card)
        self.recent_imports_list.setSelectionMode(
            QListWidget.SelectionMode.NoSelection
        )
        self.recent_imports_list.setFrameShape(QFrame.Shape.NoFrame)
        recent_layout = recent_card.layout()
        if recent_layout is not None:
            recent_layout.addWidget(self.recent_imports_list)

        self.content_layout.addWidget(intake_card)
        self.content_layout.addWidget(recent_card)
        self.set_recent_imports([])

    def set_recent_imports(
        self, recent_imports: Sequence[Mapping[str, Any] | str]
    ) -> None:
        """Replace the recent-imports list with normalized entries."""
        self._recent_imports = [
            self._normalize_recent_import(entry) for entry in recent_imports
        ]
        self._refresh_recent_imports_view()

    def add_recent_import(self, recent_import: Mapping[str, Any] | str) -> None:
        """Insert one recent-import entry at the top of the list."""
        normalized = self._normalize_recent_import(recent_import)
        self._recent_imports.insert(0, normalized)
        self._refresh_recent_imports_view()

    def recent_imports(self) -> list[dict[str, Any]]:
        """Return the normalized recent-import entries currently shown."""
        return [dict(entry) for entry in self._recent_imports]

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select BOM CSV Files",
            str(Path.home()),
            "CSV Files (*.csv);;All Files (*)",
        )
        self._request_import(files)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Folder Containing BOM CSV Files",
            str(Path.home()),
        )
        if not folder:
            return
        folder_path = Path(folder)
        files = sorted(
            str(path)
            for path in folder_path.rglob("*")
            if path.is_file() and path.suffix.lower() == ".csv"
        )
        self._request_import(files)

    def _handle_dropped_files(self, paths: list[str]) -> None:
        self._request_import(paths)

    def _request_import(self, paths: Sequence[str]) -> None:
        normalized_paths = self._normalize_paths(paths)
        if not normalized_paths:
            return
        self.import_requested.emit(normalized_paths)

    def _refresh_recent_imports_view(self) -> None:
        self.recent_imports_list.clear()
        if not self._recent_imports:
            placeholder = QListWidgetItem("No recent imports yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent_imports_list.addItem(placeholder)
            return

        for entry in self._recent_imports:
            label = self._format_recent_import_label(entry)
            item = QListWidgetItem(label)
            tooltip = self._format_recent_import_tooltip(entry)
            if tooltip:
                item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, dict(entry))
            self.recent_imports_list.addItem(item)

    def _normalize_recent_import(
        self, recent_import: Mapping[str, Any] | str
    ) -> dict[str, Any]:
        if isinstance(recent_import, str):
            path = recent_import
            return {
                "label": Path(path).name or path,
                "paths": [path],
                "detail": path,
            }

        normalized = dict(recent_import)
        paths = self._normalize_paths(normalized.get("paths", []))
        if not paths:
            path = normalized.get("path")
            if isinstance(path, str) and path:
                paths = [path]
        normalized["paths"] = paths
        label = normalized.get("label")
        if not isinstance(label, str) or not label.strip():
            if paths:
                normalized["label"] = Path(paths[0]).name or paths[0]
            else:
                normalized["label"] = "Recent import"
        detail = normalized.get("detail")
        if not isinstance(detail, str):
            normalized["detail"] = ""
        return normalized

    def _format_recent_import_label(self, entry: Mapping[str, Any]) -> str:
        label = str(entry.get("label", "Recent import"))
        paths = entry.get("paths", [])
        path_count = (
            len(paths)
            if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes))
            else 0
        )
        row_count = entry.get("row_count")
        detail_parts: list[str] = []
        if isinstance(row_count, int):
            detail_parts.append(f"{row_count} rows")
        elif isinstance(row_count, str) and row_count.strip():
            detail_parts.append(f"{row_count} rows")
        if path_count > 1:
            detail_parts.append(f"{path_count} files")
        imported_at = entry.get("imported_at") or entry.get("timestamp")
        if isinstance(imported_at, str) and imported_at.strip():
            detail_parts.append(imported_at)
        elif isinstance(entry.get("detail"), str) and entry["detail"].strip():
            detail_parts.append(entry["detail"])
        if detail_parts:
            return f"{label} - {' | '.join(detail_parts)}"
        return label

    def _format_recent_import_tooltip(self, entry: Mapping[str, Any]) -> str:
        paths = entry.get("paths", [])
        if isinstance(paths, Sequence) and not isinstance(paths, (str, bytes)) and paths:
            return "\n".join(str(path) for path in paths)
        detail = entry.get("detail")
        if isinstance(detail, str):
            return detail
        return ""

    def _normalize_paths(self, paths: Sequence[str] | str | Any) -> list[str]:
        if isinstance(paths, str):
            cleaned = paths.strip()
            return [cleaned] if cleaned else []
        normalized_paths: list[str] = []
        for path in paths:
            if not isinstance(path, str):
                continue
            cleaned = path.strip()
            if cleaned and cleaned not in normalized_paths:
                normalized_paths.append(cleaned)
        return normalized_paths
