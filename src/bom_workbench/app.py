"""Application bootstrap for BOM Workbench."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Any, Mapping, Sequence

import structlog

from bom_workbench import __version__
from bom_workbench.application import (
    BomEnrichmentUseCase,
    EventBus,
    ExportBomUseCase,
    FindPartsUseCase,
    JobCancelled,
    JobCompleted,
    JobFailed,
    PartSearchCriteria,
    ReplacementConfirmationRequired,
    JobManager,
    JobPaused,
    JobProgress,
    JobQueued,
    JobResumed,
    JobStarted,
    ImportBomUseCase,
    ImportCompleted,
    ImportFailed,
    ImportStarted,
    ProviderManagementService,
)
from bom_workbench.domain.entities import BomRow, Job
from bom_workbench.domain.ports import ExportOptions
from bom_workbench.domain.value_objects import ColumnMapping
from bom_workbench.infrastructure.csv import CsvParser
from bom_workbench.infrastructure.csv.column_matcher import ColumnMatcher
from bom_workbench.infrastructure.csv.normalizer import RowNormalizer
from bom_workbench.infrastructure.exporters import XlsxExporter
from bom_workbench.infrastructure.providers import (
    AnthropicProviderAdapter,
    OpenAIProviderAdapter,
)
from bom_workbench.infrastructure.persistence import (
    DatabaseSettings,
    create_db_and_tables,
    create_engine_from_settings,
    create_session_factory,
)
from bom_workbench.infrastructure.persistence.bom_repository import SqliteBomRepository
from bom_workbench.infrastructure.persistence.job_repository import SqliteJobRepository
from bom_workbench.infrastructure.retrievers import LcscEvidenceRetriever
from bom_workbench.infrastructure.secrets import KeyringSecretStore

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]

if QApplication is not None:
    from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QWidget

    from bom_workbench.ui.dialogs import ColumnMappingDialog, ImportReportDialog
    from bom_workbench.ui.inspector import RowInspector
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
    from bom_workbench.ui.theme import apply_theme
else:  # pragma: no cover
    class MainWindow:  # type: ignore[too-many-ancestors]
        """Fallback placeholder when Qt is unavailable."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            msg = "PySide6 is required to instantiate MainWindow"
            raise RuntimeError(msg)


logger = structlog.get_logger(__name__)
_LOG_LEVEL_CHOICES: tuple[str, ...] = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


def _schedule_async(awaitable: Any) -> Any:
    """Run an awaitable on the active loop, or fall back to a blocking run."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    return loop.create_task(awaitable)


def configure_logging(log_level: str = "INFO", *, http_debug: bool = False) -> None:
    """Configure safe, production-style console logging."""

    normalized_level = str(log_level).strip().upper()
    level = logging._nameToLevel.get(normalized_level, logging.INFO)  # noqa: SLF001
    logging.basicConfig(level=level, format="%(message)s", force=True)
    http_log_level = logging.INFO if http_debug else logging.WARNING
    logging.getLogger("httpx").setLevel(http_log_level)
    logging.getLogger("httpcore").setLevel(http_log_level)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logger.info(
        "logging_configured",
        log_level=normalized_level,
        http_debug=http_debug,
        http_log_level=logging.getLevelName(http_log_level),
    )


def _parse_args(argv: Sequence[str] | None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="bom-workbench")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Initialize logging and exit without starting the UI.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=_LOG_LEVEL_CHOICES,
        type=str.upper,
        help="Set application log verbosity.",
    )
    parser.add_argument(
        "--http-debug",
        action="store_true",
        help="Enable verbose httpx/httpcore logging.",
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
    """Create the shell window with default pages and inspector."""

    return MainWindow(
        pages=_build_default_pages(),
        inspector=RowInspector(),
        workspace_name="Default Workspace",
        app_name="BOM Workbench",
    )


def _coerce_paths(paths: Sequence[str]) -> list[Path]:
    unique_paths: list[Path] = []
    for raw_path in paths:
        cleaned = raw_path.strip()
        if not cleaned:
            continue
        path = Path(cleaned)
        if path not in unique_paths:
            unique_paths.append(path)
    return unique_paths


def _mapping_dict(mappings: Sequence[ColumnMapping]) -> dict[str, str]:
    return {mapping.raw_column: mapping.canonical_field for mapping in mappings}


def _mapping_list(mapping_dict: dict[str, str]) -> list[ColumnMapping]:
    mappings: list[ColumnMapping] = []
    for raw_column, canonical_field in mapping_dict.items():
        if raw_column and canonical_field:
            mappings.append(
                ColumnMapping(
                    raw_column=raw_column,
                    canonical_field=canonical_field,
                )
            )
    return mappings


def _wire_phase6_import_flow(window: MainWindow) -> None:
    db_settings = DatabaseSettings.from_env()
    engine = create_engine_from_settings(db_settings)
    create_db_and_tables(engine)
    session_factory = create_session_factory(engine)
    repository = SqliteBomRepository(session_factory)

    import_event_bus = EventBus[object]()
    import_use_case = ImportBomUseCase(
        repository=repository,
        parser=CsvParser(),
        matcher=ColumnMatcher(),
        normalizer=RowNormalizer(),
        event_bus=import_event_bus,
    )

    import_page_widget = window.page_widget("import")
    bom_table_widget = window.page_widget("bom_table")
    import_page = import_page_widget if isinstance(import_page_widget, ImportPage) else None
    bom_table_page = bom_table_widget if isinstance(bom_table_widget, BomTablePage) else None
    row_inspector = window.inspector if isinstance(window.inspector, RowInspector) else None
    state: dict[str, Any] = {"rows": [], "project_id": 0, "active_job_id": 0}

    def on_import_event(event: object) -> None:
        if isinstance(event, ImportStarted):
            window.set_status_text(f"Importing {Path(event.source_file).name}...")
            window.set_connection_state("Provider: import running")
        elif isinstance(event, ImportCompleted):
            window.set_connection_state("Provider: idle")
        elif isinstance(event, ImportFailed):
            window.set_connection_state("Provider: error")
            window.set_status_text(f"Import failed: {event.error_message}")

    import_event_bus.subscribe(on_import_event)

    def on_row_selected(row_payload: dict[str, Any]) -> None:
        if row_inspector is None:
            return
        if not row_payload:
            row_inspector.clear_row()
            window.set_status_text("No row selected")
            return

        row_inspector.set_row(row_payload)
        designator = str(row_payload.get("designator", "")).strip() or "row"
        window.set_status_text(f"Selected {designator}")

    async def run_import(source_paths: Sequence[Path]) -> None:
        if not source_paths:
            window.set_status_text("No CSV files selected")
            return

        if any(not path.exists() for path in source_paths):
            missing = [str(path) for path in source_paths if not path.exists()]
            QMessageBox.warning(
                window,
                "Missing files",
                "Some selected files were not found:\n" + "\n".join(missing),
            )
            return

        first_source = source_paths[0]
        try:
            window.set_progress(10)
            window.set_status_text("Analyzing column mappings...")
            preview = await import_use_case.build_preview(first_source)

            dialog = ColumnMappingDialog(
                detected_mappings=_mapping_dict(preview.column_mappings),
                unmapped_columns=list(preview.unmapped_columns),
                warnings=list(preview.warnings),
                parent=window,
            )
            if dialog.exec() != int(QDialog.DialogCode.Accepted):
                window.set_status_text("Import cancelled")
                window.set_progress(0)
                return

            selected_mappings = _mapping_list(dialog.selected_mappings)
            if not selected_mappings:
                QMessageBox.warning(
                    window,
                    "Missing mappings",
                    "At least one column mapping is required to continue.",
                )
                window.set_status_text("Import blocked: no mappings selected")
                window.set_progress(0)
                return

            window.set_status_text("Importing CSV files...")
            window.set_progress(30)
            project, report, rows = await import_use_case.import_files(
                source_paths,
                mappings=selected_mappings,
                project_name=first_source.stem,
            )
            state["rows"] = list(rows)
            state["project_id"] = int(project.id or 0)
            state["active_job_id"] = 0

            if bom_table_page is not None:
                bom_table_page.set_rows(rows)
                if rows:
                    bom_table_page.table_view.selectRow(0)

            if import_page is not None:
                import_page.add_recent_import(
                    {
                        "label": project.name or first_source.name,
                        "paths": [str(path) for path in source_paths],
                        "row_count": report.imported_count,
                    }
                )

            window.show_page("bom_table")
            window.set_row_counts(total=report.imported_count, enriched=0)
            window.set_progress(100)
            window.set_status_text(
                f"Imported {report.imported_count} rows from {len(source_paths)} file(s)"
            )

            report_dialog = ImportReportDialog(
                file_name=Path(report.source_file).name,
                rows_imported=report.imported_count,
                warnings=list(report.warnings),
                errors=[],
                unmapped_columns=list(report.unmapped_columns),
                parent=window,
            )
            report_dialog.exec()
        except Exception as exc:  # pragma: no cover - UI error path
            logger.exception("import_failed", error=str(exc))
            QMessageBox.critical(
                window,
                "Import Failed",
                f"Import failed: {exc}",
            )
            window.set_status_text("Import failed")
            window.set_progress(0)

    def request_import(paths: Sequence[str]) -> None:
        source_paths = _coerce_paths(paths)
        if not source_paths:
            window.set_status_text("No CSV files selected")
            return
        _schedule_async(run_import(source_paths))

    def choose_files() -> None:
        file_names, _selected_filter = QFileDialog.getOpenFileNames(
            window,
            "Select BOM CSV Files",
            str(Path.cwd()),
            "CSV Files (*.csv);;All Files (*)",
        )
        request_import(file_names)

    def choose_folder() -> None:
        folder_name = QFileDialog.getExistingDirectory(
            window,
            "Select BOM Folder",
            str(Path.cwd()),
        )
        if not folder_name:
            return

        folder = Path(folder_name)
        csv_paths = sorted(
            str(path)
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() == ".csv"
        )
        if not csv_paths:
            QMessageBox.information(
                window,
                "No CSV Files",
                f"No CSV files were found in {folder}.",
            )
            return

        request_import(csv_paths)

    def on_import_requested() -> None:
        window.show_page("import")
        choose_files()

    window.import_requested.connect(on_import_requested)

    if import_page is not None:
        import_page.import_requested.connect(request_import)

    if bom_table_page is not None:
        bom_table_page.row_selected.connect(on_row_selected)

    window._phase6_event_bus = import_event_bus  # type: ignore[attr-defined]
    window._phase6_import_use_case = import_use_case  # type: ignore[attr-defined]
    window._phase6_repository = repository  # type: ignore[attr-defined]
    window._phase6_session_factory = session_factory  # type: ignore[attr-defined]
    window._phase6_state = state  # type: ignore[attr-defined]
    window._phase6_choose_files = choose_files  # type: ignore[attr-defined]
    window._phase6_choose_folder = choose_folder  # type: ignore[attr-defined]

    window.set_status_text("Ready for import")
    window.set_row_counts(total=0, enriched=0)
    window.set_connection_state("Provider: idle")


def _wire_phase7_provider_flow(window: MainWindow) -> None:
    provider_widget = window.page_widget("providers")
    providers_page = provider_widget if isinstance(provider_widget, ProvidersPage) else None
    if providers_page is None:
        return

    secret_store = KeyringSecretStore()
    provider_service = ProviderManagementService(secret_store)
    provider_service.register_adapter(OpenAIProviderAdapter())
    provider_service.register_adapter(AnthropicProviderAdapter())

    capability_by_provider: dict[str, dict[str, object]] = {}
    for provider in provider_service.list_providers():
        capabilities = provider_service.get_capabilities(provider)
        capability_by_provider[provider] = {
            "show_reasoning_controls": capabilities.supports_reasoning_control
            or bool(capabilities.reasoning_levels),
            "show_connection_test": True,
            "show_model_refresh": capabilities.supports_model_discovery,
            "reasoning_label": capabilities.reasoning_control_name or "Reasoning",
            "reasoning_help_text": (
                "Capability-driven provider reasoning control."
                if capabilities.supports_reasoning_control or capabilities.reasoning_levels
                else ""
            ),
        }
        providers_page.apply_provider_capabilities(
            provider,
            capability_by_provider[provider],
        )
        providers_page.set_provider_models(provider, [])
        providers_page.set_connection_status_text(provider, "Not checked")

    async def initialize_provider_state() -> None:
        for provider in provider_service.list_providers():
            state = await provider_service.describe_provider(provider)
            if state.has_stored_key:
                providers_page.set_connection_status_text(
                    provider,
                    "Stored key available",
                )
            else:
                providers_page.set_connection_status_text(
                    provider,
                    "No key stored",
                )
        if secret_store.status.available:
            window.set_connection_state(
                f"Provider: keyring ready ({secret_store.status.backend_name})"
            )
        else:
            window.set_connection_state("Provider: keyring unavailable")

    async def test_provider_connection(provider: str, api_key: str) -> None:
        key = api_key.strip()
        if not key:
            stored = await provider_service.retrieve_provider_key(provider)
            key = stored or ""

        if not key:
            providers_page.set_connection_status_text(
                provider,
                "Missing API key",
            )
            QMessageBox.warning(
                window,
                "Missing API key",
                f"Add an API key for {provider} before testing connection.",
            )
            return

        providers_page.set_connection_status_text(provider, "Testing connection...")
        result = await provider_service.test_provider_connection(provider, key)
        if result.success:
            await provider_service.store_provider_key(provider, key)
            providers_page.set_connection_status_text(
                provider,
                f"Connected ({int(result.latency_ms)} ms)",
            )
            window.set_connection_state(f"Provider: {provider} connected")
            return

        providers_page.set_connection_status_text(
            provider,
            f"Failed: {result.message}",
        )
        window.set_connection_state(f"Provider: {provider} failed")

    async def refresh_models(provider: str, api_key: str) -> None:
        key = api_key.strip()
        if not key:
            stored = await provider_service.retrieve_provider_key(provider)
            key = stored or ""

        if not key:
            providers_page.set_connection_status_text(provider, "Missing API key")
            return

        providers_page.set_connection_status_text(provider, "Refreshing models...")
        models = await provider_service.discover_models(provider, key)
        providers_page.set_provider_models(
            provider,
            [model.id for model in models],
        )
        if models:
            providers_page.set_connection_status_text(
                provider,
                f"Loaded {len(models)} model(s)",
            )
        else:
            providers_page.set_connection_status_text(provider, "No models discovered")

    async def save_provider_settings(payload: dict[str, dict[str, Any]]) -> None:
        saved = 0
        for provider, provider_payload in payload.items():
            api_key = str(provider_payload.get("api_key", "")).strip()
            if api_key:
                await provider_service.store_provider_key(provider, api_key)
                saved += 1
            elif not bool(provider_payload.get("enabled", True)):
                await provider_service.delete_provider_key(provider)
        window.set_status_text(f"Saved provider settings ({saved} key(s) updated)")

    def on_test_connection(provider: str, api_key: str) -> None:
        _schedule_async(test_provider_connection(provider, api_key))

    def on_refresh_models(provider: str, api_key: str) -> None:
        _schedule_async(refresh_models(provider, api_key))

    def on_save_settings(payload: dict[str, dict[str, Any]]) -> None:
        _schedule_async(save_provider_settings(payload))

    providers_page.test_connection_clicked.connect(on_test_connection)
    providers_page.refresh_models_clicked.connect(on_refresh_models)
    providers_page.save_settings_clicked.connect(on_save_settings)

    _schedule_async(initialize_provider_state())
    window._phase7_provider_service = provider_service  # type: ignore[attr-defined]
    window._phase7_secret_store = secret_store  # type: ignore[attr-defined]


def _wire_phase8_enrichment_flow(window: MainWindow) -> None:
    repository = getattr(window, "_phase6_repository", None)
    session_factory = getattr(window, "_phase6_session_factory", None)
    state = getattr(window, "_phase6_state", None)
    if not isinstance(repository, SqliteBomRepository):
        return
    if session_factory is None or not isinstance(state, dict):
        return

    bom_table_widget = window.page_widget("bom_table")
    jobs_widget = window.page_widget("jobs")
    bom_table_page = bom_table_widget if isinstance(bom_table_widget, BomTablePage) else None
    jobs_page = jobs_widget if isinstance(jobs_widget, JobsPage) else None

    enrichment_use_case = BomEnrichmentUseCase(repository, LcscEvidenceRetriever())
    job_repository = SqliteJobRepository(session_factory=session_factory)
    job_event_bus = EventBus[object]()
    job_manager = JobManager(job_repository, event_bus=job_event_bus, max_concurrency=3)

    async def refresh_project_rows() -> list[BomRow]:
        project_id = int(state.get("project_id", 0) or 0)
        if project_id <= 0:
            return []

        rows = await repository.list_rows_by_project(project_id)
        state["rows"] = list(rows)
        if bom_table_page is not None:
            bom_table_page.set_rows(rows)
            if rows and not bom_table_page.table_view.currentIndex().isValid():
                bom_table_page.table_view.selectRow(0)
        window.set_row_counts(
            total=len(rows),
            enriched=sum(1 for row in rows if row.row_state == "enriched"),
        )
        return rows

    def selected_row_id() -> int | None:
        if bom_table_page is None:
            return None
        current = bom_table_page.table_view.currentIndex()
        if not current.isValid():
            return None
        payload = bom_table_page.table_model.row_at(current.row()) or {}
        value = payload.get("id")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    async def submit_enrichment_job(row_ids: Sequence[int]) -> None:
        normalized_ids = [row_id for row_id in row_ids if row_id > 0]
        if not normalized_ids:
            window.set_status_text("No rows selected for enrichment")
            return

        project_id = int(state.get("project_id", 0) or 0)
        if project_id <= 0:
            window.set_status_text("Import a BOM project before enrichment")
            return

        job = Job(
            job_type="enrichment",
            state="pending",
            project_id=project_id,
            target_row_ids=",".join(str(row_id) for row_id in normalized_ids),
            total_rows=len(normalized_ids),
            provider_name="deterministic",
            model_name="deterministic-parser",
        )

        async def executor(row_id: int) -> bool:
            row = await enrichment_use_case.enrich_row(row_id)
            return row.row_state != "failed"

        persisted = await job_manager.submit(job, executor)
        state["active_job_id"] = int(persisted.id or 0)
        window.show_page("jobs")
        window.set_progress(0)
        window.set_status_text(f"Queued enrichment job {persisted.id} ({len(normalized_ids)} rows)")
        if jobs_page is not None:
            jobs_page.upsert_job(persisted)

    async def on_job_event(event: object) -> None:
        if isinstance(event, JobQueued):
            if jobs_page is not None:
                saved = await job_repository.get(event.job_id)
                if saved is not None:
                    jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} queued")
            return

        if isinstance(event, JobStarted):
            if jobs_page is not None:
                saved = await job_repository.get(event.job_id)
                if saved is not None:
                    jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} running")
            return

        if isinstance(event, JobProgress):
            saved = await job_repository.get(event.job_id)
            if saved is not None:
                processed = saved.completed_rows + saved.failed_rows
                progress = int((processed / max(saved.total_rows, 1)) * 100)
                window.set_progress(progress)
                if jobs_page is not None:
                    jobs_page.upsert_job(saved)
                window.set_status_text(
                    f"Job {event.job_id}: {processed}/{saved.total_rows} rows processed"
                )
            return

        if isinstance(event, JobCompleted):
            saved = await job_repository.get(event.job_id)
            if saved is not None and jobs_page is not None:
                jobs_page.upsert_job(saved)
            await refresh_project_rows()
            window.set_progress(100)
            window.set_status_text(
                f"Job {event.job_id} finished ({event.completed_rows} ok, {event.failed_rows} failed)"
            )
            return

        if isinstance(event, JobFailed):
            saved = await job_repository.get(event.job_id)
            if saved is not None and jobs_page is not None:
                jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} failed: {event.error_message}")
            return

        if isinstance(event, JobCancelled):
            saved = await job_repository.get(event.job_id)
            if saved is not None and jobs_page is not None:
                jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} cancelled")
            return

        if isinstance(event, JobPaused):
            window.set_status_text(f"Job {event.job_id} paused")
            return

        if isinstance(event, JobResumed):
            window.set_status_text(f"Job {event.job_id} resumed")

    job_event_bus.subscribe(on_job_event)

    async def enrich_selected() -> None:
        row_id = selected_row_id()
        if row_id is None:
            window.set_status_text("Select a row to enrich")
            return
        await submit_enrichment_job([row_id])

    async def enrich_all() -> None:
        row_ids = [int(row.id) for row in state.get("rows", []) if isinstance(row.id, int)]
        await submit_enrichment_job(row_ids)

    async def pause_active_job() -> None:
        job_id = int(state.get("active_job_id", 0) or 0)
        if job_id <= 0:
            return
        saved = await job_manager.pause(job_id)
        if jobs_page is not None:
            jobs_page.upsert_job(saved)

    async def resume_active_job() -> None:
        job_id = int(state.get("active_job_id", 0) or 0)
        if job_id <= 0:
            return
        saved = await job_manager.resume(job_id)
        if jobs_page is not None:
            jobs_page.upsert_job(saved)

    async def cancel_active_job() -> None:
        job_id = int(state.get("active_job_id", 0) or 0)
        if job_id <= 0:
            return
        saved = await job_manager.cancel(job_id)
        if jobs_page is not None:
            jobs_page.upsert_job(saved)

    async def retry_failed_rows() -> None:
        rows = await refresh_project_rows()
        failed_row_ids = [int(row.id) for row in rows if row.row_state == "failed" and row.id is not None]
        if not failed_row_ids:
            window.set_status_text("No failed rows to retry")
            return
        await submit_enrichment_job(failed_row_ids)

    if bom_table_page is not None:
        bom_table_page.enrich_selected_button.clicked.connect(
            lambda: _schedule_async(enrich_selected())
        )
        bom_table_page.enrich_all_button.clicked.connect(
            lambda: _schedule_async(enrich_all())
        )

    window.enrich_selected_requested.connect(lambda: _schedule_async(enrich_selected()))
    window.enrich_all_requested.connect(lambda: _schedule_async(enrich_all()))

    if jobs_page is not None:
        jobs_page.pause_all_requested.connect(lambda: _schedule_async(pause_active_job()))
        jobs_page.resume_all_requested.connect(lambda: _schedule_async(resume_active_job()))
        jobs_page.cancel_all_requested.connect(lambda: _schedule_async(cancel_active_job()))
        jobs_page.retry_failed_requested.connect(lambda: _schedule_async(retry_failed_rows()))
        jobs_page.clear_requested.connect(lambda: window.set_progress(0))

    window._phase8_enrichment_use_case = enrichment_use_case  # type: ignore[attr-defined]
    window._phase8_job_repository = job_repository  # type: ignore[attr-defined]
    window._phase8_job_manager = job_manager  # type: ignore[attr-defined]
    window._phase8_job_event_bus = job_event_bus  # type: ignore[attr-defined]


def _wire_phase9_part_finder_flow(window: MainWindow) -> None:
    repository = getattr(window, "_phase6_repository", None)
    state = getattr(window, "_phase6_state", None)
    if not isinstance(repository, SqliteBomRepository):
        return
    if not isinstance(state, dict):
        return

    bom_table_widget = window.page_widget("bom_table")
    part_finder_widget = window.page_widget("part_finder")
    bom_table_page = bom_table_widget if isinstance(bom_table_widget, BomTablePage) else None
    part_finder_page = (
        part_finder_widget if isinstance(part_finder_widget, PartFinderPage) else None
    )
    if part_finder_page is None:
        return

    find_parts_use_case = FindPartsUseCase(repository, LcscEvidenceRetriever())

    def _context_row_payload(criteria: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        if criteria is not None:
            context = criteria.get("context_row")
            if isinstance(context, Mapping):
                return dict(context)

        payload = state.get("selected_row_payload")
        if isinstance(payload, Mapping):
            return dict(payload)

        if bom_table_page is None:
            return None
        current = bom_table_page.table_view.currentIndex()
        if not current.isValid():
            return None
        row_payload = bom_table_page.table_model.row_at(current.row())
        return dict(row_payload) if row_payload else None

    def _context_row_id(criteria: Mapping[str, Any] | None = None) -> int | None:
        payload = _context_row_payload(criteria)
        if not payload:
            return None
        value = payload.get("id")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    async def _refresh_project_rows() -> list[BomRow]:
        project_id = int(state.get("project_id", 0) or 0)
        if project_id <= 0:
            return []

        rows = await repository.list_rows_by_project(project_id)
        state["rows"] = list(rows)
        if bom_table_page is not None:
            bom_table_page.set_rows(rows)
        window.set_row_counts(
            total=len(rows),
            enriched=sum(1 for row in rows if row.row_state == "enriched"),
        )
        return rows

    def _candidate_display_name(candidate: Mapping[str, Any]) -> str:
        for key in ("candidate", "lcsc_part_number", "part_number", "mpn", "description"):
            value = str(candidate.get(key, "")).strip()
            if value:
                return value
        return "candidate"

    def _replacement_rows_payload(results: Sequence[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for result in results:
            candidate = result.candidate
            lifecycle = (
                candidate.lifecycle_status.value
                if hasattr(candidate.lifecycle_status, "value")
                else str(candidate.lifecycle_status)
            )
            confidence = (
                candidate.confidence.value
                if hasattr(candidate.confidence, "value")
                else str(candidate.confidence)
            )
            score_value = float(result.score)
            rows.append(
                {
                    "candidate": candidate.lcsc_part_number
                    or candidate.part_number
                    or candidate.mpn
                    or candidate.description,
                    "mpn": candidate.mpn,
                    "footprint": candidate.footprint,
                    "value": candidate.value_summary or candidate.description,
                    "manufacturer": candidate.manufacturer,
                    "stock": candidate.stock_qty
                    if candidate.stock_qty is not None
                    else candidate.stock_status,
                    "score": f"{score_value:.3f}",
                    "candidate_payload": candidate.model_dump(mode="json"),
                    "match_score": score_value,
                    "match_explanation": result.explanation,
                    "requires_manual_review": bool(result.requires_manual_review),
                    "lifecycle_status": lifecycle,
                    "stock_status": candidate.stock_status,
                    "stock_qty": candidate.stock_qty,
                    "confidence": confidence,
                    "warnings": list(candidate.warnings),
                    "description": candidate.description,
                    "lcsc_part_number": candidate.lcsc_part_number,
                    "lcsc_link": candidate.lcsc_link,
                    "part_number": candidate.part_number,
                }
            )
        return rows

    async def _search_from_selected() -> None:
        row_id = _context_row_id()
        if row_id is None:
            part_finder_page.set_status_message("Select a BOM row before searching.")
            return

        part_finder_page.set_status_message("Searching candidates from selected row...")
        results = await find_parts_use_case.find_candidates_for_row(row_id)
        payload = _replacement_rows_payload(results)
        part_finder_page.set_candidates(payload)
        if not results:
            part_finder_page.set_status_message("No replacement candidates found.")
            return

        needs_review = sum(1 for result in results if result.requires_manual_review)
        part_finder_page.set_status_message(
            f"Found {len(results)} candidates ({needs_review} need manual review)."
        )

    async def _search_with_criteria(criteria: Mapping[str, Any]) -> None:
        context_row_id = _context_row_id(criteria)
        part_finder_page.set_status_message("Searching candidates...")
        results = await find_parts_use_case.find_candidates(
            row_id=context_row_id,
            criteria=PartSearchCriteria(
                part_number=str(criteria.get("part_number", "")).strip(),
                footprint=str(criteria.get("footprint", "")).strip(),
                value=str(criteria.get("value", "")).strip(),
                manufacturer=str(criteria.get("manufacturer", "")).strip(),
            ),
        )
        payload = _replacement_rows_payload(results)
        part_finder_page.set_candidates(payload)
        if not results:
            part_finder_page.set_status_message("No replacement candidates found.")
            return
        part_finder_page.set_status_message(f"Found {len(results)} candidates.")

    async def _apply_candidate(candidate_row: Mapping[str, Any]) -> None:
        row_id = _context_row_id()
        if row_id is None:
            part_finder_page.set_status_message("No selected BOM row to apply replacement.")
            return

        candidate_payload = candidate_row.get("candidate_payload")
        if not isinstance(candidate_payload, Mapping):
            part_finder_page.set_status_message("Invalid candidate payload.")
            return

        candidate_name = _candidate_display_name(candidate_row)
        confirm = QMessageBox.question(
            window,
            "Confirm Replacement",
            (
                f"Apply replacement '{candidate_name}' to selected BOM row?\n\n"
                "This action updates the row and marks replacement as user accepted."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            part_finder_page.set_status_message("Replacement cancelled.")
            return

        try:
            result = await find_parts_use_case.apply_replacement(
                row_id,
                dict(candidate_payload),
                confirmed=True,
            )
        except ReplacementConfirmationRequired:
            part_finder_page.set_status_message("Replacement requires explicit confirmation.")
            return
        except Exception as exc:
            logger.exception("replacement_apply_failed", error=str(exc), row_id=row_id)
            part_finder_page.set_status_message(f"Failed to apply replacement: {exc}")
            return

        await _refresh_project_rows()
        part_finder_page.set_status_message(
            f"Applied replacement {result.candidate.mpn or result.candidate.lcsc_part_number}."
        )
        window.set_status_text(
            f"Replacement applied to row {result.row.designator or result.row.id}"
        )

    def _on_table_row_selected(row_payload: dict[str, Any]) -> None:
        if row_payload:
            state["selected_row_payload"] = dict(row_payload)
            part_finder_page.set_context_row(row_payload)
        else:
            state["selected_row_payload"] = None
            part_finder_page.set_context_row(None)

    part_finder_page.search_from_selected_requested.connect(
        lambda: _schedule_async(_search_from_selected())
    )
    part_finder_page.search_requested.connect(
        lambda criteria: _schedule_async(_search_with_criteria(criteria))
    )
    part_finder_page.apply_candidate_requested.connect(
        lambda candidate: _schedule_async(_apply_candidate(candidate))
    )
    part_finder_page.candidate_selected.connect(
        lambda candidate: part_finder_page.set_status_message(
            (
                "Candidate selected - "
                + _candidate_display_name(candidate)
                + (
                    " (manual review recommended)"
                    if bool(candidate.get("requires_manual_review"))
                    else ""
                )
            )
        )
    )

    if bom_table_page is not None:
        bom_table_page.row_selected.connect(_on_table_row_selected)

    window._phase9_find_parts_use_case = find_parts_use_case  # type: ignore[attr-defined]


def _wire_phase10_export_flow(window: MainWindow) -> None:
    repository = getattr(window, "_phase6_repository", None)
    state = getattr(window, "_phase6_state", None)
    if not isinstance(repository, SqliteBomRepository):
        return
    if not isinstance(state, dict):
        return

    export_widget = window.page_widget("export")
    bom_table_widget = window.page_widget("bom_table")
    export_page = export_widget if isinstance(export_widget, ExportPage) else None
    bom_table_page = bom_table_widget if isinstance(bom_table_widget, BomTablePage) else None
    if export_page is None:
        return

    export_use_case = ExportBomUseCase(XlsxExporter())

    default_filtered_columns = [
        "designator",
        "quantity",
        "comment",
        "footprint",
        "lcsc_part_number",
        "manufacturer",
        "mpn",
        "lifecycle_status",
        "row_state",
    ]

    async def _project_rows() -> list[BomRow]:
        project_id = int(state.get("project_id", 0) or 0)
        if project_id <= 0:
            return []
        rows = await repository.list_rows_by_project(project_id)
        state["rows"] = list(rows)
        return rows

    def _filtered_columns() -> list[str]:
        if bom_table_page is None:
            return list(default_filtered_columns)

        raw_columns = getattr(bom_table_page.table_model, "_columns", [])
        columns: list[str] = []
        for value in raw_columns:
            if not isinstance(value, tuple) or len(value) != 2:
                continue
            field_name = str(value[1]).strip()
            if field_name:
                columns.append(field_name)
        return columns or list(default_filtered_columns)

    def _default_output_path(target: str) -> Path:
        target_slug = target.replace("current_filtered_view", "filtered_view")
        project_name = str(state.get("project_name", "")).strip() or "bom"
        return Path.cwd() / f"{project_name}_{target_slug}.xlsx"

    def _result_payload(result: Any) -> dict[str, Any]:
        return {
            "output_path": str(result.output_path),
            "rows_exported": int(result.rows_exported),
            "sheets_created": list(result.sheets_created),
            "warnings": list(result.warnings),
            "duration_seconds": float(result.duration_seconds),
            "file_size_bytes": int(result.file_size_bytes),
        }

    async def _run_export(payload: Mapping[str, Any], output_path: Path) -> None:
        rows = await _project_rows()
        if not rows:
            export_page.set_status_message("No BOM rows available to export.")
            window.set_status_text("Export blocked: no rows")
            window.set_progress(0)
            return

        options_payload = payload.get("options")
        options_map = options_payload if isinstance(options_payload, Mapping) else {}
        export_options = ExportOptions(
            include_metadata_sheet=bool(options_map.get("include_metadata_sheet", True)),
            apply_color_coding=bool(options_map.get("apply_color_coding", True)),
            preserve_hyperlinks=bool(options_map.get("preserve_hyperlinks", True)),
            sanitize_formulas=bool(options_map.get("sanitize_formulas", True)),
        )

        target = str(payload.get("target", "procurement_bom")).strip().lower()
        filtered_columns = (
            _filtered_columns()
            if target in {"filtered_view", "current_filtered_view"}
            else None
        )

        window.set_progress(20)
        export_page.set_status_message("Export in progress...")
        window.set_status_text("Export in progress...")

        try:
            result = await export_use_case.export(
                rows,
                output_path,
                export_options,
                target=target,
                filtered_columns=filtered_columns,
            )
        except Exception as exc:  # pragma: no cover - UI error path
            logger.exception("export_failed", error=str(exc), target=target)
            export_page.set_status_message(f"Export failed: {exc}")
            window.set_status_text("Export failed")
            window.set_progress(0)
            QMessageBox.critical(window, "Export Failed", f"Export failed: {exc}")
            return

        payload_result = _result_payload(result)
        export_page.set_last_export_result(payload_result)
        export_page.set_status_message(
            f"Exported {result.rows_exported} row(s) to {Path(result.output_path).name}."
        )
        window.set_status_text(f"Export complete: {Path(result.output_path).name}")
        window.set_progress(100)

    def _on_export_requested(payload: dict[str, Any]) -> None:
        project_id = int(state.get("project_id", 0) or 0)
        if project_id <= 0:
            export_page.set_status_message("Import a BOM project before exporting.")
            window.set_status_text("Export blocked: no project")
            return

        target = str(payload.get("target", "procurement_bom")).strip().lower()
        output_name, _selected_filter = QFileDialog.getSaveFileName(
            window,
            "Export Workbook",
            str(_default_output_path(target)),
            "Excel Workbook (*.xlsx);;All Files (*)",
        )
        if not output_name:
            export_page.set_status_message("Export cancelled.")
            window.set_status_text("Export cancelled")
            return

        output_path = Path(output_name)
        if output_path.suffix.lower() != ".xlsx":
            output_path = output_path.with_suffix(".xlsx")
        _schedule_async(_run_export(payload, output_path))

    export_page.export_requested.connect(_on_export_requested)
    window.export_requested.connect(
        lambda: export_page.set_status_message(
            "Configure export options and click 'Export to File...'."
        )
    )

    window._phase10_export_use_case = export_use_case  # type: ignore[attr-defined]


def bootstrap(argv: Sequence[str] | None = None) -> int:
    """Start the application and return a process exit code."""

    parsed_args, qt_argv = _parse_args(argv)
    configure_logging(parsed_args.log_level, http_debug=parsed_args.http_debug)

    logger.info(
        "application_starting",
        app="bom_workbench",
        version=__version__,
        headless=parsed_args.headless,
        log_level=parsed_args.log_level,
        http_debug=parsed_args.http_debug,
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

    try:
        from qasync import QEventLoop
    except ImportError:
        window = create_main_window()
        _wire_phase6_import_flow(window)
        _wire_phase7_provider_flow(window)
        _wire_phase8_enrichment_flow(window)
        _wire_phase9_part_finder_flow(window)
        _wire_phase10_export_flow(window)
        window.show()
        logger.info("qasync_unavailable", fallback="qt_event_loop")
        return int(app.exec())

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app.aboutToQuit.connect(loop.stop)

    window = create_main_window()
    _wire_phase6_import_flow(window)
    _wire_phase7_provider_flow(window)
    _wire_phase8_enrichment_flow(window)
    _wire_phase9_part_finder_flow(window)
    _wire_phase10_export_flow(window)
    window.show()

    with loop:
        loop.run_forever()
    return 0
