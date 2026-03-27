"""Application bootstrap for BOM Workbench."""

from __future__ import annotations

import argparse
import asyncio
import logging
from importlib.util import find_spec
from typing import Sequence

import structlog

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:  # pragma: no cover - exercised only when Qt is unavailable
    QtCore = None  # type: ignore[assignment]
    QtWidgets = None  # type: ignore[assignment]

from bom_workbench import __version__

HAS_QT = QtWidgets is not None


def configure_logging() -> None:
    """Configure safe, production-style console logging."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _parse_args(argv: Sequence[str] | None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="bom-workbench")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Initialize logging and exit without starting the Qt event loop.",
    )
    return parser.parse_known_args(None if argv is None else list(argv))


if HAS_QT:
    from bom_workbench.ui.inspector import RowInspector
    from bom_workbench.ui.pages import (
        BomTablePage,
        ExportPage,
        ImportPage,
        JobsPage,
        PartFinderPage,
        ProvidersPage,
        SettingsPage,
    )

    class MainWindow(QtWidgets.QMainWindow):
        """Primary BOM Workbench window shell."""

        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("mainWindow")
            self.setWindowTitle("BOM Workbench")
            self.resize(1440, 960)

            self.pages: dict[str, QtWidgets.QWidget] = {}
            self.nav_buttons: list[QtWidgets.QPushButton] = []

            container = QtWidgets.QWidget(self)
            root_layout = QtWidgets.QVBoxLayout(container)
            root_layout.setContentsMargins(16, 16, 16, 16)
            root_layout.setSpacing(12)

            root_layout.addWidget(self._build_top_bar())
            root_layout.addWidget(self._build_body())
            root_layout.addWidget(self._build_status_bar())

            self.setCentralWidget(container)
            self._set_current_page(0)

        def _build_top_bar(self) -> QtWidgets.QFrame:
            frame = QtWidgets.QFrame(self)
            frame.setObjectName("topBar")
            layout = QtWidgets.QHBoxLayout(frame)
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(12)

            title_block = QtWidgets.QVBoxLayout()
            title = QtWidgets.QLabel("BOM Workbench", frame)
            title.setObjectName("windowTitleLabel")
            title.setStyleSheet("font-size: 20px; font-weight: 700;")
            subtitle = QtWidgets.QLabel(
                "Phase 5 UI shell with page stubs, inspector, and async bootstrap.",
                frame,
            )
            subtitle.setWordWrap(True)
            title_block.addWidget(title)
            title_block.addWidget(subtitle)
            layout.addLayout(title_block, stretch=1)

            workspace_label = QtWidgets.QLabel("Workspace: not loaded", frame)
            workspace_label.setObjectName("workspaceLabel")
            layout.addWidget(workspace_label)

            version_label = QtWidgets.QLabel(f"v{__version__}", frame)
            version_label.setObjectName("versionLabel")
            layout.addWidget(version_label)
            return frame

        def _build_body(self) -> QtWidgets.QSplitter:
            splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
            splitter.setObjectName("mainSplitter")
            splitter.addWidget(self._build_nav_rail())
            splitter.addWidget(self._build_page_stack())
            splitter.addWidget(self._build_inspector_panel())
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setStretchFactor(2, 0)
            splitter.setSizes([220, 900, 320])
            return splitter

        def _build_nav_rail(self) -> QtWidgets.QFrame:
            frame = QtWidgets.QFrame(self)
            frame.setObjectName("navRail")
            frame.setMinimumWidth(180)
            frame.setMaximumWidth(240)
            layout = QtWidgets.QVBoxLayout(frame)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)

            nav_items = [
                "Import",
                "BOM Table",
                "Part Finder",
                "Providers",
                "Jobs",
                "Export",
                "Settings",
            ]
            button_group = QtWidgets.QButtonGroup(frame)
            button_group.setExclusive(True)

            for index, label in enumerate(nav_items):
                button = QtWidgets.QPushButton(label, frame)
                button.setCheckable(True)
                button.clicked.connect(
                    lambda checked=False, i=index: self._set_current_page(i)
                )
                button_group.addButton(button)
                layout.addWidget(button)
                self.nav_buttons.append(button)

            layout.addStretch(1)
            footer = QtWidgets.QLabel("Navigation", frame)
            footer.setAlignment(
                QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignBottom
            )
            layout.addWidget(footer)
            return frame

        def _build_page_stack(self) -> QtWidgets.QStackedWidget:
            stack = QtWidgets.QStackedWidget(self)
            stack.setObjectName("pageStack")

            page_classes = [
                ("Import", ImportPage),
                ("BOM Table", BomTablePage),
                ("Part Finder", PartFinderPage),
                ("Providers", ProvidersPage),
                ("Jobs", JobsPage),
                ("Export", ExportPage),
                ("Settings", SettingsPage),
            ]
            for name, page_cls in page_classes:
                page = page_cls()
                self.pages[name] = page
                stack.addWidget(page)

            stack.currentChanged.connect(self._sync_nav_state)
            self.page_stack = stack
            return stack

        def _build_inspector_panel(self) -> QtWidgets.QFrame:
            frame = QtWidgets.QFrame(self)
            frame.setObjectName("inspectorPanel")
            frame.setMinimumWidth(260)
            frame.setMaximumWidth(360)
            layout = QtWidgets.QVBoxLayout(frame)
            layout.setContentsMargins(12, 12, 12, 12)
            self.inspector = RowInspector(frame)
            layout.addWidget(self.inspector)
            layout.addStretch(1)
            return frame

        def _build_status_bar(self) -> QtWidgets.QFrame:
            frame = QtWidgets.QFrame(self)
            frame.setObjectName("statusBar")
            layout = QtWidgets.QHBoxLayout(frame)
            layout.setContentsMargins(12, 8, 12, 8)
            layout.setSpacing(12)

            self.status_message = QtWidgets.QLabel("Ready", frame)
            self.quick_stats = QtWidgets.QLabel("Rows: 0 | Enriched: 0", frame)
            layout.addWidget(self.status_message, stretch=1)
            layout.addWidget(self.quick_stats)
            return frame

        def _set_current_page(self, index: int) -> None:
            if hasattr(self, "page_stack"):
                self.page_stack.setCurrentIndex(index)
            self._sync_nav_state(index)

        def _sync_nav_state(self, index: int) -> None:
            for button_index, button in enumerate(self.nav_buttons):
                button.setChecked(button_index == index)

else:  # pragma: no cover - exercised only when Qt is unavailable

    class MainWindow:  # type: ignore[too-many-ancestors]
        """Placeholder used when Qt is not installed."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            raise RuntimeError("PySide6 is required to instantiate MainWindow")


def bootstrap(argv: Sequence[str] | None = None) -> int:
    """Start the application and return a process exit code."""
    configure_logging()
    logger = structlog.get_logger(__name__)

    parsed_args, qt_argv = _parse_args(argv)
    logger.info(
        "application_starting",
        app="bom_workbench",
        version=__version__,
        headless=parsed_args.headless,
    )

    if parsed_args.headless:
        logger.info("headless_mode_enabled", fallback="no_ui_loop")
        return 0

    if not HAS_QT:
        logger.info("qt_runtime_unavailable", fallback="headless_startup")
        return 0

    if find_spec("qasync") is None:
        logger.info("qasync_unavailable", fallback="qt_event_loop")

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(["bom-workbench", *qt_argv])

    window = MainWindow()
    window.show()

    if find_spec("qasync") is None:
        return int(app.exec())

    from qasync import QEventLoop

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app.aboutToQuit.connect(loop.stop)
    with loop:
        loop.run_forever()
    return 0
