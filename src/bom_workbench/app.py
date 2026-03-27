"""Application bootstrap for BOM Workbench."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Sequence

import structlog

from bom_workbench import __version__

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]

if QApplication is not None:
    from bom_workbench.ui.main_window import MainWindow
    from bom_workbench.ui.pages import (
        BomTablePage,
        ExportPage,
        ImportPage,
        JobsPage,
        PartFinderPage,
        ProvidersPage,
        SettingsPage,
    )
    from bom_workbench.ui.inspector import RowInspector
    from bom_workbench.ui.theme import apply_theme
else:  # pragma: no cover
    class MainWindow:  # type: ignore[too-many-ancestors]
        """Fallback placeholder when Qt is unavailable."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            msg = "PySide6 is required to instantiate MainWindow"
            raise RuntimeError(msg)


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
        help="Initialize logging and exit without starting the UI.",
    )
    return parser.parse_known_args(None if argv is None else list(argv))


def _build_default_pages() -> dict[str, object]:
    return {
        "import": ImportPage(),
        "bom_table": BomTablePage(),
        "part_finder": PartFinderPage(),
        "providers": ProvidersPage(),
        "jobs": JobsPage(),
        "export": ExportPage(),
        "settings": SettingsPage(),
    }


def create_main_window() -> MainWindow:
    """Create the phase-5 shell window with default pages and inspector."""
    return MainWindow(
        pages=_build_default_pages(),
        inspector=RowInspector(),
        workspace_name="Default Workspace",
        app_name="BOM Workbench",
    )


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

    if QApplication is None:
        logger.info("qt_runtime_unavailable", fallback="headless_startup")
        return 0

    app = QApplication.instance()
    if app is None:
        app = QApplication(["bom-workbench", *qt_argv])

    apply_theme(app)
    window = create_main_window()
    window.show()

    try:
        from qasync import QEventLoop
    except ImportError:
        logger.info("qasync_unavailable", fallback="qt_event_loop")
        return int(app.exec())

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app.aboutToQuit.connect(loop.stop)
    with loop:
        loop.run_forever()
    return 0
