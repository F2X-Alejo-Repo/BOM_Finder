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
        self.setProperty("page", True)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)

        hero = QtWidgets.QFrame(self)
        hero.setObjectName("PageHero")
        hero_layout = QtWidgets.QVBoxLayout(hero)
        hero_layout.setContentsMargins(28, 24, 28, 24)
        hero_layout.setSpacing(8)

        eyebrow = QtWidgets.QLabel("BOM Workbench", hero)
        eyebrow.setObjectName("pageEyebrow")
        hero_layout.addWidget(eyebrow)

        heading = QtWidgets.QLabel(title, hero)
        heading.setObjectName("pageHeading")
        heading.setWordWrap(True)
        hero_layout.addWidget(heading)

        description = QtWidgets.QLabel(subtitle, hero)
        description.setObjectName("pageSubtitle")
        description.setWordWrap(True)
        hero_layout.addWidget(description)
        root.addWidget(hero)

        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        root.addLayout(self.content_layout)
        root.addStretch(1)


def create_card(title: str, lines: Sequence[str]) -> QtWidgets.QFrame:
    """Create a compact informational card."""
    card = QtWidgets.QFrame()
    card.setObjectName("InfoCard")
    card.setProperty("card", True)
    layout = QtWidgets.QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(8)

    title_label = QtWidgets.QLabel(title, card)
    title_label.setObjectName("cardTitle")
    title_label.setWordWrap(True)
    layout.addWidget(title_label)

    for line in lines:
        label = QtWidgets.QLabel(line, card)
        label.setObjectName("cardBody")
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
