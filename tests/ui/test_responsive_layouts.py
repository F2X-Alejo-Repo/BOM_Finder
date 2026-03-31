"""Responsive layout checks for core desktop UI surfaces."""

from __future__ import annotations

import pytest


def _ensure_app(monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("PySide6")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(["bom-workbench-test"])
    return app


def test_simple_pages_are_scrollable(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_app(monkeypatch)

    from PySide6 import QtWidgets
    from bom_workbench.ui.pages import ImportPage, JobsPage, PartFinderPage

    for page in (ImportPage(), JobsPage(), PartFinderPage()):
        assert isinstance(page.scroll_area, QtWidgets.QScrollArea)
        assert page.scroll_area.widgetResizable() is True


def test_bom_table_uses_adaptive_column_resize_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_app(monkeypatch)

    from PySide6 import QtWidgets
    from bom_workbench.ui.pages.bom_table_page import BomTablePage

    page = BomTablePage()
    header = page.table_view.horizontalHeader()

    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(2) == QtWidgets.QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(5) == QtWidgets.QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(7) == QtWidgets.QHeaderView.ResizeMode.ResizeToContents


def test_jobs_page_uses_splitter_for_table_and_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_app(monkeypatch)

    from PySide6 import QtCore, QtWidgets
    from bom_workbench.ui.pages.jobs_page import JobsPage

    page = JobsPage()
    splitters = page.findChildren(QtWidgets.QSplitter)

    assert splitters
    assert any(
        splitter.orientation() == QtCore.Qt.Orientation.Vertical for splitter in splitters
    )
