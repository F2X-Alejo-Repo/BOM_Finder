"""Import page stub."""

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from . import SimplePage, create_card


class ImportPage(SimplePage):
    """Page for BOM import entry points."""

    def __init__(self) -> None:
        super().__init__(
            "BOM Import",
            "Drag CSV files here or use the file picker to start a new import.",
        )

        drop_zone = QtWidgets.QFrame(self)
        drop_zone.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        drop_layout = QtWidgets.QVBoxLayout(drop_zone)
        drop_layout.setContentsMargins(18, 18, 18, 18)
        drop_layout.setSpacing(10)

        drop_title = QtWidgets.QLabel("DropZone", drop_zone)
        drop_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        drop_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        drop_hint = QtWidgets.QLabel(
            "Drag KiCad CSV files here, or browse for one or more files.",
            drop_zone,
        )
        drop_hint.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        drop_hint.setWordWrap(True)

        button_row = QtWidgets.QHBoxLayout()
        browse_files = QtWidgets.QPushButton("Browse Files", drop_zone)
        browse_folder = QtWidgets.QPushButton("Browse Folder", drop_zone)
        button_row.addWidget(browse_files)
        button_row.addWidget(browse_folder)

        drop_layout.addWidget(drop_title)
        drop_layout.addWidget(drop_hint)
        drop_layout.addLayout(button_row)

        recent_imports = create_card(
            "Recent Imports",
            [
                "sample_bom_standard.csv - 142 rows - 2 minutes ago",
                "power_board.csv - 89 rows - 1 hour ago",
                "sensor_pack.csv - 16 rows - yesterday",
            ],
        )

        self.content_layout.addWidget(drop_zone)
        self.content_layout.addWidget(recent_imports)
