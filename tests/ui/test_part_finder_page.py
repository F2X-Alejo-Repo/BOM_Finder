"""Focused UI tests for the part finder page contract."""

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


def test_part_finder_page_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """The part finder page should expose the Phase 9 UI contract."""
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.part_finder_page import PartFinderPage

    page = PartFinderPage()

    search_from_selected_events: list[bool] = []
    search_events: list[dict[str, object]] = []
    apply_events: list[dict[str, object]] = []

    page.search_from_selected_requested.connect(
        lambda: search_from_selected_events.append(True)
    )
    page.search_requested.connect(search_events.append)
    page.apply_candidate_requested.connect(apply_events.append)

    page.set_context_row(
        {
            "designator": "R12",
            "mpn": "RC0402FR-0710KL",
            "footprint": "0402",
            "value": "10k",
            "manufacturer": "Yageo",
        }
    )
    page.part_number_edit.setText("RC0402FR-0710KL")
    page.footprint_edit.setText("0402")
    page.value_edit.setText("10k")
    page.manufacturer_edit.setText("Yageo")
    page.active_only_check.setChecked(True)
    page.in_stock_check.setChecked(False)
    page.lcsc_available_check.setChecked(True)
    page.set_status_message("Ready")

    candidates = [
        {
            "candidate": "Yageo RC0402FR-0710KL",
            "mpn": "RC0402FR-0710KL",
            "footprint": "0402",
            "value": "10k",
            "manufacturer": "Yageo",
            "stock": 124,
            "score": 0.98,
        },
        {
            "candidate": "KOA RK73H",
            "mpn": "RK73H1JTTD1002F",
            "footprint": "0402",
            "value": "10k",
            "manufacturer": "KOA",
            "stock": 52,
            "score": 0.81,
        },
    ]
    page.set_candidates(candidates)

    page.search_from_selected_button.click()
    page.search_button.click()
    page.candidate_view.selectRow(0)
    page.apply_selected_button.click()

    assert search_from_selected_events == [True]
    assert search_events
    criteria = search_events[0]
    assert criteria["part_number"] == "RC0402FR-0710KL"
    assert criteria["filters"]["active_only"] is True
    assert criteria["context_row"]["designator"] == "R12"
    assert page.candidate_model.rowCount() == 2
    assert page.candidate_view.currentIndex().row() == 0
    assert apply_events[-1]["mpn"] == "RC0402FR-0710KL"
    assert "Ready" == page.status_label.text()
    assert "R12" in page.context_summary.text()
