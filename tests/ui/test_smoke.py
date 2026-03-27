"""UI smoke tests for Phase 5."""

from __future__ import annotations

import pytest

from bom_workbench.app import MainWindow, bootstrap


def test_bootstrap_headless_returns_zero() -> None:
    """Headless bootstrap should exit immediately for CI."""
    assert bootstrap(["--headless"]) == 0


def test_main_window_can_be_instantiated_offscreen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Qt shell should build without entering the event loop."""
    pytest.importorskip("PySide6")

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(["bom-workbench-test"])

    window = MainWindow()

    assert window.windowTitle() == "BOM Workbench"
    assert window.page_stack.count() == 7
    assert len(window.nav_buttons) == 7
    assert window.inspector is not None

    window.close()
    app.processEvents()
