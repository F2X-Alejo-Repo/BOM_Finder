"""Page widgets for the BOM Workbench UI."""

from __future__ import annotations

from typing import Sequence

from PySide6 import QtWidgets

__all__ = [
    "SimplePage",
    "create_card",
    "BomTableModel",
    "BomTablePage",
    "ExportPage",
    "ImportPage",
    "JobsPage",
    "PartFinderPage",
    "ProvidersPage",
    "SettingsPage",
]


class SimplePage(QtWidgets.QWidget):
    """Shared page shell with a heading and content layout."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setObjectName(f"{title.lower().replace(' ', '')}Page")

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        heading = QtWidgets.QLabel(title, self)
        heading.setObjectName("pageHeading")
        heading.setStyleSheet("font-size: 22px; font-weight: 700;")
        heading.setWordWrap(True)
        root.addWidget(heading)

        description = QtWidgets.QLabel(subtitle, self)
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        root.addWidget(description)

        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setSpacing(12)
        root.addLayout(self.content_layout)
        root.addStretch(1)


def create_card(title: str, lines: Sequence[str]) -> QtWidgets.QGroupBox:
    """Create a compact informational card."""
    card = QtWidgets.QGroupBox(title)
    layout = QtWidgets.QVBoxLayout(card)
    layout.setContentsMargins(12, 16, 12, 12)
    layout.setSpacing(6)
    for line in lines:
        label = QtWidgets.QLabel(line, card)
        label.setWordWrap(True)
        layout.addWidget(label)
    return card


from .bom_table_page import BomTableModel, BomTablePage
from .export_page import ExportPage
from .import_page import ImportPage
from .jobs_page import JobsPage
from .part_finder_page import PartFinderPage
from .providers_page import ProvidersPage
from .settings_page import SettingsPage
