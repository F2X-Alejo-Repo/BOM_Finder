"""Part finder page stub."""

from __future__ import annotations

from PySide6 import QtWidgets

from . import SimplePage, create_card


class PartFinderPage(SimplePage):
    """Page for replacement search and candidate review."""

    def __init__(self) -> None:
        super().__init__(
            "Part Finder",
            "Search for replacements by part number, footprint, or electrical value.",
        )

        search_card = QtWidgets.QGroupBox("Search Criteria", self)
        search_layout = QtWidgets.QFormLayout(search_card)
        part_number = QtWidgets.QLineEdit(search_card)
        footprint = QtWidgets.QLineEdit(search_card)
        value = QtWidgets.QLineEdit(search_card)
        part_number.setPlaceholderText("MPN or LCSC part number")
        footprint.setPlaceholderText("0402, LQFP-64, etc.")
        value.setPlaceholderText("100nF, 10k, etc.")
        search_layout.addRow("Part # / MPN", part_number)
        search_layout.addRow("Footprint", footprint)
        search_layout.addRow("Value", value)

        filter_row = QtWidgets.QHBoxLayout()
        filter_row.addWidget(QtWidgets.QCheckBox("Active only", search_card))
        filter_row.addWidget(QtWidgets.QCheckBox("In stock", search_card))
        filter_row.addWidget(QtWidgets.QCheckBox("LCSC available", search_card))
        filter_row.addStretch(1)

        results = create_card(
            "Results",
            [
                "Candidate results will appear here once the search service is wired.",
                "Users will be able to compare candidates and apply replacements.",
            ],
        )
        candidate_list = QtWidgets.QListWidget(self)
        candidate_list.addItem("Samsung CL05B104KO5 - score 0.95 - in stock")
        candidate_list.addItem("Yageo CC0402KRX7R9 - score 0.88 - active")
        candidate_list.addItem("Murata GRM155R71C104KA88 - score 0.82 - alt")

        search_button_row = QtWidgets.QHBoxLayout()
        search_button_row.addWidget(QtWidgets.QPushButton("Search from Selected BOM Row", self))
        search_button_row.addWidget(QtWidgets.QPushButton("Search", self))
        search_button_row.addStretch(1)

        self.content_layout.addWidget(search_card)
        self.content_layout.addLayout(filter_row)
        self.content_layout.addLayout(search_button_row)
        self.content_layout.addWidget(results)
        self.content_layout.addWidget(candidate_list)
