"""Main application shell for the BOM Workbench UI."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

PAGE_KEYS: Final[tuple[str, ...]] = (
    "import",
    "bom_table",
    "part_finder",
    "providers",
    "jobs",
    "export",
    "settings",
)

PAGE_LABELS: Final[dict[str, str]] = {
    "import": "Import",
    "bom_table": "BOM Table",
    "part_finder": "Part Finder",
    "providers": "Providers",
    "jobs": "Jobs",
    "export": "Export",
    "settings": "Settings",
}

PAGE_SUBTITLES: Final[dict[str, str]] = {
    "import": "Bring BOM files in cleanly and get straight to structured work.",
    "bom_table": "Inspect the normalized BOM and push rows through enrichment with confidence.",
    "part_finder": "Compare replacement candidates without losing context from the selected row.",
    "providers": "Control model providers, credentials, and runtime behavior from one place.",
    "jobs": "Watch long-running work and understand what the app is doing in real time.",
    "export": "Produce polished procurement output instead of raw tables.",
    "settings": "Tune workspace defaults and operational behavior.",
}


class MainWindow(QMainWindow):
    """Primary shell window for the BOM Workbench application."""

    page_changed = Signal(str)
    import_requested = Signal()
    export_requested = Signal()
    search_requested = Signal()
    refresh_requested = Signal()
    enrich_selected_requested = Signal()
    enrich_all_requested = Signal()
    settings_requested = Signal()
    inspector_close_requested = Signal()

    def __init__(
        self,
        *,
        pages: Mapping[str, QWidget] | None = None,
        inspector: QWidget | None = None,
        workspace_name: str = "Workspace",
        app_name: str = "BOM Workbench",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_widgets: dict[str, QWidget] = {}
        self._page_buttons: dict[str, QToolButton] = {}
        self._shortcuts: list[QShortcut] = []
        self._workspace_name = workspace_name
        self._app_name = app_name
        self._last_nav_width = 240
        self._last_inspector_width = 340

        self.setObjectName("MainWindow")
        self.setWindowTitle(app_name)
        self.resize(1480, 980)
        self.setMinimumSize(920, 680)

        self._build_app_bar()
        self._build_central_shell()
        self._build_status_bar()
        self._build_shortcuts()

        for page_key in PAGE_KEYS:
            widget = (
                pages[page_key]
                if pages is not None and page_key in pages
                else self._create_placeholder_page(page_key)
            )
            self.set_page_widget(page_key, widget)

        self.set_inspector_widget(inspector or self._create_placeholder_inspector())
        self.show_page(PAGE_KEYS[0])
        self._sync_panel_toggle_buttons()
        self._update_responsive_chrome()

    @property
    def current_page_key(self) -> str:
        """Return the current routed page key."""
        current_widget = self.page_stack.currentWidget()
        for page_key, widget in self._page_widgets.items():
            if widget is current_widget:
                return page_key
        return PAGE_KEYS[0]

    @property
    def nav_buttons(self) -> list[QToolButton]:
        """Expose navigation buttons for smoke tests and wiring."""
        return [self._page_buttons[key] for key in PAGE_KEYS]

    @property
    def inspector(self) -> QWidget:
        """Return the active inspector widget."""
        return self.inspector_stack.currentWidget()

    def page_widget(self, page_key: str) -> QWidget | None:
        """Return the widget registered for a page key."""
        return self._page_widgets.get(page_key)

    def set_page_widget(self, page_key: str, widget: QWidget) -> None:
        """Register or replace a page widget for the given page key."""
        if page_key not in PAGE_KEYS:
            raise KeyError(f"Unknown page key: {page_key}")

        previous_widget = self._page_widgets.get(page_key)
        current_page = self.current_page_key if previous_widget is not None else None
        if previous_widget is None:
            self.page_stack.addWidget(widget)
        else:
            index = self.page_stack.indexOf(previous_widget)
            if index < 0:
                self.page_stack.addWidget(widget)
            else:
                self.page_stack.insertWidget(index, widget)
            self.page_stack.removeWidget(previous_widget)
            previous_widget.setParent(None)

        self._page_widgets[page_key] = widget
        self._page_buttons[page_key].setEnabled(True)
        if current_page == page_key:
            self.page_stack.setCurrentWidget(widget)

    def set_pages(self, pages: Mapping[str, QWidget]) -> None:
        """Register a batch of page widgets."""
        for page_key, widget in pages.items():
            self.set_page_widget(page_key, widget)

    def show_page(self, page_key: str) -> None:
        """Route the shell to a page key."""
        widget = self._page_widgets.get(page_key)
        if widget is None:
            raise KeyError(f"Unknown page key: {page_key}")
        self.page_stack.setCurrentWidget(widget)
        for key, button in self._page_buttons.items():
            button.setChecked(key == page_key)
        self.page_changed.emit(page_key)
        self._update_status_page_label(page_key)

    def next_page(self) -> None:
        """Advance to the next available page."""
        self._show_offset_page(1)

    def previous_page(self) -> None:
        """Move to the previous available page."""
        self._show_offset_page(-1)

    def clear_inspector(self) -> None:
        """Reset the inspector area back to its placeholder state."""
        self.inspector_stack.setCurrentWidget(self._inspector_placeholder)
        self.inspector_close_requested.emit()

    def set_inspector_widget(self, widget: QWidget) -> None:
        """Replace the inspector content widget."""
        if self.inspector_stack.indexOf(widget) == -1:
            self.inspector_stack.addWidget(widget)
        self.inspector_stack.setCurrentWidget(widget)

    def set_status_text(self, text: str) -> None:
        """Update the main status text in the footer."""
        self.status_text_label.setText(text)

    def set_row_counts(
        self, *, total: int | None = None, enriched: int | None = None
    ) -> None:
        """Update the footer row counters."""
        if total is not None:
            self.total_rows_label.setText(f"Rows: {total}")
        if enriched is not None:
            self.enriched_rows_label.setText(f"Enriched: {enriched}")

    def set_progress(self, value: int, maximum: int = 100) -> None:
        """Update the job progress bar."""
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)

    def set_connection_state(self, text: str) -> None:
        """Update the provider or connection indicator."""
        self.connection_label.setText(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_responsive_chrome()

    def _build_app_bar(self) -> None:
        app_bar = QFrame(self)
        app_bar.setObjectName("AppBar")
        app_bar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(app_bar)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        top_row = QWidget(app_bar)
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(16)

        title_block = QWidget(app_bar)
        title_layout = QVBoxLayout(title_block)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)

        brand = QLabel("BOM WORKBENCH", title_block)
        brand.setObjectName("BrandBadge")

        title = QLabel(self._app_name, title_block)
        title.setObjectName("AppTitle")

        self.page_context_label = QLabel(PAGE_LABELS[PAGE_KEYS[0]], title_block)
        self.page_context_label.setObjectName("AppContext")
        self.page_context_detail = QLabel(PAGE_SUBTITLES[PAGE_KEYS[0]], title_block)
        self.page_context_detail.setObjectName("AppContextDetail")
        self.page_context_detail.setWordWrap(True)

        title_layout.addWidget(brand)
        title_layout.addWidget(title)
        title_layout.addWidget(self.page_context_label)
        title_layout.addWidget(self.page_context_detail)
        title_block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        action_cluster = QWidget(app_bar)
        action_layout = QHBoxLayout(action_cluster)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(10)

        self.import_quick_button = QPushButton("Import", action_cluster)
        self.import_quick_button.setObjectName("PrimaryChromeButton")
        self.import_quick_button.clicked.connect(self._emit_import_requested)

        self.enrich_quick_button = QPushButton("Enrich Selected", action_cluster)
        self.enrich_quick_button.setObjectName("SecondaryChromeButton")
        self.enrich_quick_button.clicked.connect(self._emit_enrich_selected_requested)

        self.export_quick_button = QPushButton("Export", action_cluster)
        self.export_quick_button.setObjectName("SecondaryChromeButton")
        self.export_quick_button.clicked.connect(self._emit_export_requested)

        action_layout.addWidget(self.import_quick_button)
        action_layout.addWidget(self.enrich_quick_button)
        action_layout.addWidget(self.export_quick_button)

        chrome_controls = QWidget(app_bar)
        chrome_layout = QHBoxLayout(chrome_controls)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(10)

        self.theme_button = QPushButton("Noir", app_bar)
        self.theme_button.setObjectName("themeButton")
        self.theme_button.setCheckable(True)
        self.theme_button.setToolTip("Dark theme styling is currently active")
        self.theme_button.setChecked(True)

        self.workspace_button = QPushButton(self._workspace_name, app_bar)
        self.workspace_button.setObjectName("workspaceButton")
        self.workspace_button.setToolTip("Workspace selector placeholder")

        self.nav_toggle_button = QPushButton("Navigation", app_bar)
        self.nav_toggle_button.setObjectName("SecondaryChromeButton")
        self.nav_toggle_button.setCheckable(True)
        self.nav_toggle_button.setChecked(True)
        self.nav_toggle_button.setToolTip("Show or hide the navigation rail")
        self.nav_toggle_button.toggled.connect(self._toggle_nav_rail)

        self.inspector_toggle_button = QPushButton("Inspector", app_bar)
        self.inspector_toggle_button.setObjectName("SecondaryChromeButton")
        self.inspector_toggle_button.setCheckable(True)
        self.inspector_toggle_button.setChecked(True)
        self.inspector_toggle_button.setToolTip("Show or hide the row inspector panel")
        self.inspector_toggle_button.toggled.connect(self._toggle_inspector_panel)

        chrome_layout.addWidget(self.nav_toggle_button)
        chrome_layout.addWidget(self.inspector_toggle_button)
        chrome_layout.addWidget(self.workspace_button)
        chrome_layout.addWidget(self.theme_button)

        top_layout.addWidget(title_block, 1)
        top_layout.addStretch(1)
        top_layout.addWidget(chrome_controls, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top_row)

        bottom_row = QWidget(app_bar)
        bottom_layout = QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(action_cluster)
        bottom_layout.addStretch(1)
        layout.addWidget(bottom_row)

        self.setMenuWidget(app_bar)

    def _build_central_shell(self) -> None:
        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setObjectName("MainSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(10)
        self.splitter.splitterMoved.connect(self._handle_splitter_moved)

        self.nav_rail = self._build_nav_rail()
        self.page_stack = QStackedWidget(self.splitter)
        self.page_stack.setObjectName("PageStack")
        self.page_stack.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.page_stack.setMinimumWidth(480)

        self.inspector_frame = QFrame(self.splitter)
        self.inspector_frame.setObjectName("InspectorPanel")
        self.inspector_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.inspector_frame.setMinimumWidth(260)
        self.inspector_frame.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        inspector_layout = QVBoxLayout(self.inspector_frame)
        inspector_layout.setContentsMargins(12, 12, 12, 12)
        inspector_layout.setSpacing(12)

        self.inspector_scroll_area = QScrollArea(self.inspector_frame)
        self.inspector_scroll_area.setObjectName("InspectorScrollArea")
        self.inspector_scroll_area.setWidgetResizable(True)
        self.inspector_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.inspector_stack = QStackedWidget(self.inspector_frame)
        self.inspector_stack.setObjectName("InspectorStack")
        self._inspector_placeholder = self._create_placeholder_inspector()
        self.inspector_stack.addWidget(self._inspector_placeholder)
        self.inspector_scroll_area.setWidget(self.inspector_stack)
        inspector_layout.addWidget(self.inspector_scroll_area)

        self.splitter.addWidget(self.nav_rail)
        self.splitter.addWidget(self.page_stack)
        self.splitter.addWidget(self.inspector_frame)
        self.splitter.setCollapsible(0, True)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, True)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([240, 980, 340])

        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(self.splitter)
        self.setCentralWidget(central)

    def _build_nav_rail(self) -> QFrame:
        rail = QFrame(self)
        rail.setObjectName("NavRail")
        rail.setFrameShape(QFrame.Shape.StyledPanel)
        rail.setMinimumWidth(208)
        rail.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(10)

        rail_title = QLabel("Navigation", rail)
        rail_title.setObjectName("NavSectionTitle")
        rail_detail = QLabel(
            "Core flows stay close at hand so the workspace feels focused instead of crowded.",
            rail,
        )
        rail_detail.setObjectName("NavSectionDetail")
        rail_detail.setWordWrap(True)
        self.nav_section_detail = rail_detail
        layout.addWidget(rail_title)
        layout.addWidget(rail_detail)

        for page_key in PAGE_KEYS:
            button = QToolButton(rail)
            button.setObjectName(f"NavButton_{page_key}")
            button.setProperty("class", "navButton")
            button.setText(PAGE_LABELS[page_key])
            button.setToolTip(PAGE_LABELS[page_key])
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda checked=False, key=page_key: self.show_page(key)
            )
            self._page_buttons[page_key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        version_label = QLabel("Polished workspace shell", rail)
        version_label.setObjectName("NavFooterLabel")
        version_label.setProperty("muted", True)
        self.nav_footer_label = version_label
        layout.addWidget(version_label)
        return rail

    def _build_status_bar(self) -> None:
        status_bar = QStatusBar(self)
        status_bar.setObjectName("StatusPanel")
        status_bar.setSizeGripEnabled(True)
        self.setStatusBar(status_bar)

        self.status_text_label = QLabel("Ready", status_bar)
        self.status_text_label.setObjectName("StatusPrimary")
        self.total_rows_label = QLabel("Rows: 0", status_bar)
        self.enriched_rows_label = QLabel("Enriched: 0", status_bar)
        self.connection_label = QLabel("Provider: idle", status_bar)
        self.total_rows_label.setObjectName("StatusMetric")
        self.enriched_rows_label.setObjectName("StatusMetric")
        self.connection_label.setObjectName("StatusMetric")
        self.progress_bar = QProgressBar(status_bar)
        self.progress_bar.setObjectName("FooterProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(160)
        self.progress_bar.setMaximumWidth(320)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self.progress_bar.setTextVisible(True)

        status_bar.addWidget(self.status_text_label, 1)
        status_bar.addPermanentWidget(self.progress_bar)
        status_bar.addPermanentWidget(self.total_rows_label)
        status_bar.addPermanentWidget(self.enriched_rows_label)
        status_bar.addPermanentWidget(self.connection_label)

    def _build_shortcuts(self) -> None:
        self._add_shortcut("Ctrl+I", self._emit_import_requested)
        self._add_shortcut("Ctrl+E", self._emit_export_requested)
        self._add_shortcut("Ctrl+F", self._emit_search_requested)
        self._add_shortcut("Ctrl+R", self._emit_enrich_selected_requested)
        self._add_shortcut("Ctrl+Shift+R", self._emit_enrich_all_requested)
        self._add_shortcut("F5", self._emit_refresh_requested)
        self._add_shortcut("Escape", self.clear_inspector)
        self._add_shortcut("Ctrl+,", self._emit_settings_requested)
        self._add_shortcut("Ctrl+Tab", self.next_page)
        self._add_shortcut("Ctrl+Shift+Tab", self.previous_page)

        for index, page_key in enumerate(PAGE_KEYS, start=1):
            self._add_shortcut(
                f"Ctrl+{index}", lambda key=page_key: self.show_page(key)
            )

    def _add_shortcut(self, sequence: str, handler: Callable[[], None]) -> None:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(handler)
        self._shortcuts.append(shortcut)

    def _emit_import_requested(self) -> None:
        self.import_requested.emit()
        self.show_page("import")

    def _emit_export_requested(self) -> None:
        self.export_requested.emit()
        self.show_page("export")

    def _emit_search_requested(self) -> None:
        self.search_requested.emit()

    def _emit_refresh_requested(self) -> None:
        self.refresh_requested.emit()

    def _emit_enrich_selected_requested(self) -> None:
        self.enrich_selected_requested.emit()

    def _emit_enrich_all_requested(self) -> None:
        self.enrich_all_requested.emit()

    def _emit_settings_requested(self) -> None:
        self.settings_requested.emit()
        self.show_page("settings")

    def _update_status_page_label(self, page_key: str) -> None:
        self.page_context_label.setText(PAGE_LABELS[page_key])
        self.page_context_detail.setText(PAGE_SUBTITLES.get(page_key, ""))
        self.status_text_label.setText(f"Viewing {PAGE_LABELS[page_key]}")

    def _handle_splitter_moved(self, pos: int, index: int) -> None:
        del pos, index
        sizes = self.splitter.sizes()
        if len(sizes) >= 3:
            if sizes[0] > 0:
                self._last_nav_width = sizes[0]
            if sizes[2] > 0:
                self._last_inspector_width = sizes[2]
        self._sync_panel_toggle_buttons()

    def _toggle_nav_rail(self, visible: bool) -> None:
        self._set_splitter_panel_visible(
            0, visible, fallback_size=max(self._last_nav_width, 220)
        )

    def _toggle_inspector_panel(self, visible: bool) -> None:
        self._set_splitter_panel_visible(
            2, visible, fallback_size=max(self._last_inspector_width, 300)
        )

    def _set_splitter_panel_visible(
        self, panel_index: int, visible: bool, *, fallback_size: int
    ) -> None:
        sizes = self.splitter.sizes()
        if panel_index >= len(sizes):
            return

        if visible:
            if sizes[panel_index] > 0:
                return
            sizes[panel_index] = fallback_size
            self.splitter.setSizes(sizes)
            return

        if sizes[panel_index] > 0:
            if panel_index == 0:
                self._last_nav_width = sizes[panel_index]
            elif panel_index == 2:
                self._last_inspector_width = sizes[panel_index]
        sizes[panel_index] = 0
        self.splitter.setSizes(sizes)

    def _sync_panel_toggle_buttons(self) -> None:
        sizes = self.splitter.sizes()
        nav_visible = len(sizes) >= 1 and sizes[0] > 0
        inspector_visible = len(sizes) >= 3 and sizes[2] > 0
        for button, visible in (
            (getattr(self, "nav_toggle_button", None), nav_visible),
            (getattr(self, "inspector_toggle_button", None), inspector_visible),
        ):
            if button is None:
                continue
            button.blockSignals(True)
            button.setChecked(visible)
            button.blockSignals(False)

    def _update_responsive_chrome(self) -> None:
        compact_width = self.width() < 1220
        tighter_width = self.width() < 1120
        self.page_context_detail.setVisible(not compact_width)
        if hasattr(self, "nav_section_detail"):
            self.nav_section_detail.setVisible(not tighter_width)
        if hasattr(self, "nav_footer_label"):
            self.nav_footer_label.setVisible(not tighter_width)

    def _show_offset_page(self, offset: int) -> None:
        current_index = PAGE_KEYS.index(self.current_page_key)
        next_index = (current_index + offset) % len(PAGE_KEYS)
        self.show_page(PAGE_KEYS[next_index])

    def _create_placeholder_page(self, page_key: str) -> QWidget:
        placeholder = QFrame(self.page_stack)
        placeholder.setObjectName(f"Placeholder_{page_key}")
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title = QLabel(PAGE_LABELS[page_key], placeholder)
        title.setObjectName("PlaceholderHeading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Page content will be injected by the caller.", placeholder)
        subtitle.setObjectName("PlaceholderBody")
        subtitle.setProperty("muted", True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        return placeholder

    def _create_placeholder_inspector(self) -> QWidget:
        placeholder = QFrame(
            self.inspector_frame if hasattr(self, "inspector_frame") else self
        )
        placeholder.setObjectName("InspectorPlaceholder")
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("Row Inspector", placeholder)
        title.setObjectName("InspectorPlaceholderHeading")
        body = QLabel("Select a BOM row to inspect details.", placeholder)
        body.setObjectName("InspectorPlaceholderBody")
        body.setWordWrap(True)
        body.setProperty("muted", True)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)
        return placeholder
