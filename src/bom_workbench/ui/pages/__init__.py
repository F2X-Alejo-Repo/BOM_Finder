"""Page widgets for the BOM Workbench UI."""

from __future__ import annotations

from typing import Sequence

from PySide6 import QtCore, QtWidgets

__all__ = [
    "SimplePage",
    "configure_data_table",
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
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setObjectName("PageScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        root.addWidget(self.scroll_area)

        scroll_host = QtWidgets.QWidget(self.scroll_area)
        scroll_host.setObjectName("PageScrollHost")
        self.scroll_area.setWidget(scroll_host)

        scroll_layout = QtWidgets.QVBoxLayout(scroll_host)
        scroll_layout.setContentsMargins(24, 20, 24, 24)
        scroll_layout.setSpacing(0)

        self.page_body = QtWidgets.QFrame(scroll_host)
        self.page_body.setObjectName(f"{self.objectName()}Body")
        self.page_body.setProperty("pageBody", True)
        self.page_body.setMaximumWidth(1520)
        self.page_body.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        scroll_layout.addWidget(
            self.page_body,
            1,
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop,
        )

        page_layout = QtWidgets.QVBoxLayout(self.page_body)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(18)

        hero = QtWidgets.QFrame(self.page_body)
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
        page_layout.addWidget(hero)

        self.content_layout = QtWidgets.QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(14)
        page_layout.addLayout(self.content_layout, 1)


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


def configure_data_table(
    table: QtWidgets.QTableView | QtWidgets.QTableWidget,
    *,
    stretch_column: int | None = None,
    minimum_height: int = 260,
    default_section_size: int = 160,
    minimum_section_size: int = 92,
) -> None:
    """Apply consistent sizing and interaction defaults to data-heavy tables."""

    table.setSizePolicy(
        QtWidgets.QSizePolicy.Policy.Expanding,
        QtWidgets.QSizePolicy.Policy.Expanding,
    )
    table.setMinimumHeight(minimum_height)
    table.setHorizontalScrollMode(
        QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
    )
    table.setVerticalScrollMode(
        QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel
    )
    table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    table.setWordWrap(False)
    table.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)

    header = table.horizontalHeader()
    header.setStretchLastSection(False)
    header.setSectionsMovable(True)
    header.setSectionsClickable(True)
    header.setHighlightSections(False)
    header.setMinimumSectionSize(minimum_section_size)
    header.setDefaultAlignment(
        QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
    )
    if hasattr(header, "setDefaultSectionSize"):
        header.setDefaultSectionSize(default_section_size)

    model = table.model()
    column_count = model.columnCount() if model is not None else 0
    if column_count == 0 and isinstance(table, QtWidgets.QTableWidget):
        column_count = table.columnCount()

    for column_index in range(column_count):
        header.setSectionResizeMode(
            column_index, QtWidgets.QHeaderView.ResizeMode.Interactive
        )

    target_stretch_column = stretch_column
    if target_stretch_column is None and column_count > 0:
        target_stretch_column = column_count - 1
    if target_stretch_column is not None and 0 <= target_stretch_column < column_count:
        header.setSectionResizeMode(
            target_stretch_column, QtWidgets.QHeaderView.ResizeMode.Stretch
        )

    vertical_header = table.verticalHeader()
    vertical_header.setMinimumSectionSize(28)
    vertical_header.setDefaultSectionSize(34)


from .bom_table_page import BomTableModel, BomTablePage
from .export_page import ExportPage
from .import_page import ImportPage
from .jobs_page import JobsPage
from .part_finder_page import PartFinderPage
from .providers_page import ProvidersPage
from .settings_page import SettingsPage
