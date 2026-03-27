"""Focused UI tests for the export page contract."""

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


def test_export_page_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """The export page should expose the Phase 10 UI contract."""
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.export_page import ExportPage

    page = ExportPage()

    emitted: list[dict[str, object]] = []
    page.export_requested.connect(emitted.append)

    assert page.procurement_target.isChecked() is True

    page.set_status_message("Ready to export")
    page.set_last_export_result(
        {
            "output_path": "C:/tmp/export.xlsx",
            "rows_exported": 42,
            "sheets_created": ["BOM", "Metadata"],
            "warnings": ["formula sanitized"],
            "duration_seconds": 1.23,
            "file_size_bytes": 1024,
        }
    )

    page.export_button.click()

    assert emitted
    payload = emitted[0]
    assert payload["target"] == "procurement_bom"
    assert payload["options"] == {
        "include_metadata_sheet": True,
        "apply_color_coding": True,
        "preserve_hyperlinks": True,
        "sanitize_formulas": True,
    }
    assert page.status_label.text() == "Ready to export"
    assert "C:/tmp/export.xlsx" in page.last_result_label.text()
    assert "Rows exported: 42" in page.last_result_label.text()


def test_export_page_supports_empty_result_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resetting the result summary should be safe."""
    _ensure_app(monkeypatch)

    from bom_workbench.ui.pages.export_page import ExportPage

    page = ExportPage()
    page.set_last_export_result(None)

    assert page.last_result_label.text() == "No export has been run yet."
