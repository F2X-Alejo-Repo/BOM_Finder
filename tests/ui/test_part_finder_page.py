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


def test_part_finder_page_emits_filters_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.part_finder_page import PartFinderPage

    page = PartFinderPage()
    emitted: list[dict[str, object]] = []
    page.search_requested.connect(emitted.append)

    page.set_context_row(
        {
            "id": 7,
            "designator": "R1",
            "mpn": "BASE-MPN",
            "footprint": "0603",
            "value": "10k",
            "manufacturer": "Base Parts",
        }
    )
    page.part_number_edit.setText("C12345")
    page.footprint_edit.setText("0805")
    page.value_edit.setText("10k resistor")
    page.manufacturer_edit.setText("Vendor Test")
    page.active_only_check.setChecked(True)
    page.in_stock_check.setChecked(True)
    page.lcsc_available_check.setChecked(False)

    page.search_button.click()

    assert emitted
    payload = emitted[0]
    assert payload["part_number"] == "C12345"
    assert payload["footprint"] == "0805"
    assert payload["value"] == "10k resistor"
    assert payload["manufacturer"] == "Vendor Test"
    assert payload["filters"] == {
        "active_only": True,
        "in_stock": True,
        "lcsc_available": False,
    }
    assert payload["context_row"]["id"] == 7


def test_part_finder_page_busy_state_disables_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.part_finder_page import PartFinderPage

    page = PartFinderPage()

    page.set_busy_state(searching=True)
    assert page.is_busy() is True
    assert page.search_button.isEnabled() is False
    assert page.search_from_selected_button.isEnabled() is False
    assert page.bulk_search_button.isEnabled() is False
    assert page.apply_selected_button.isEnabled() is False
    assert page.part_number_edit.isEnabled() is False

    page.set_busy_state()
    assert page.is_busy() is False
    assert page.search_button.isEnabled() is True
    assert page.search_from_selected_button.isEnabled() is True
    assert page.bulk_search_button.isEnabled() is True
    assert page.apply_selected_button.isEnabled() is True
    assert page.part_number_edit.isEnabled() is True


def test_part_finder_page_emits_bulk_scope_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.part_finder_page import PartFinderPage

    page = PartFinderPage()
    emitted: list[dict[str, object]] = []
    page.bulk_search_requested.connect(emitted.append)

    page.active_only_check.setChecked(True)
    page.in_stock_check.setChecked(False)
    page.lcsc_available_check.setChecked(True)
    page.mode_tabs.setCurrentWidget(page.bulk_tab)
    page.bulk_scope_combo.setCurrentIndex(1)
    page.bulk_search_button.click()

    assert emitted == [
        {
            "scope": "no_availability",
            "filters": {
                "active_only": True,
                "in_stock": False,
                "lcsc_available": True,
            },
        }
    ]
