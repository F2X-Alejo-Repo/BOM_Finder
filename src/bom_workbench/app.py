"""Application bootstrap for BOM Workbench."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import structlog

from bom_workbench import __version__
from bom_workbench.application import (
    BomEnrichmentUseCase,
    EnrichmentExecutionResult,
    EventBus,
    ExportBomUseCase,
    FindPartsUseCase,
    JobCancelled,
    JobCompleted,
    JobFailed,
    PartSearchCriteria,
    ReplacementConfirmationRequired,
    JobManager,
    RowExecutionResult,
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
from bom_workbench.application.llm_enrichment import (
    LLMEnrichmentRequest,
    LLMStage,
    build_grounded_llm_enrichment_stage,
)
from bom_workbench.domain.entities import BomRow, Job, ProviderConfig
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
    SqliteProviderConfigRepository,
    create_db_and_tables,
    create_engine_from_settings,
    create_session_factory,
)
from bom_workbench.infrastructure.persistence.bom_repository import SqliteBomRepository
from bom_workbench.infrastructure.persistence.job_repository import SqliteJobRepository
from bom_workbench.infrastructure.retrievers import LcscEvidenceRetriever
from bom_workbench.infrastructure.secrets import KeyringSecretStore
from bom_workbench.logging_config import LOG_LEVEL_CHOICES, configure_logging

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

_ENV_FILE_NAMES: tuple[str, ...] = (
    ".env",
    ".env.local",
    ".env.development",
    ".env.development.local",
)
_PROVIDER_API_KEY_ENV_VARS: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY", "BOM_WORKBENCH_OPENAI_API_KEY"),
    "anthropic": ("ANTHROPIC_API_KEY", "BOM_WORKBENCH_ANTHROPIC_API_KEY"),
}
_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4.1-mini",
}
_OPENAI_TIER1_MODEL_LIMITS: dict[str, dict[str, int]] = {
    # Source: official OpenAI docs for GPT-4.1 mini rate limits on 2026-03-27.
    "gpt-4.1-mini": {"rpm": 500, "tpm": 200_000},
}
_ENRICHMENT_REQUEST_TOKEN_BUDGET = 12_000
_ENRICHMENT_REQUEST_SECONDS = 5


def _schedule_async(awaitable: Any) -> Any:
    """Run an awaitable on the active loop, or fall back to a blocking run."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    return loop.create_task(awaitable)


def _provider_api_key_env_names(provider: str) -> tuple[str, ...]:
    normalized_provider = provider.strip().lower()
    fallback_name = f"{normalized_provider.upper()}_API_KEY"
    candidate_names = list(_PROVIDER_API_KEY_ENV_VARS.get(normalized_provider, ()))
    if fallback_name not in candidate_names:
        candidate_names.append(fallback_name)
    return tuple(candidate_names)


def _provider_default_model(provider: str) -> str:
    return _PROVIDER_DEFAULT_MODELS.get(provider.strip().lower(), "")


def _provider_key_search_roots() -> tuple[Path, ...]:
    roots = [Path.cwd(), Path(__file__).resolve().parents[2]]
    unique_roots: list[Path] = []
    for root in roots:
        if root not in unique_roots:
            unique_roots.append(root)
    return tuple(unique_roots)


def _parse_dotenv_assignment(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    if "=" not in stripped:
        return None

    name, value = stripped.split("=", 1)
    key = name.strip()
    if not key:
        return None

    raw_value = value.strip()
    if not raw_value:
        return key, ""

    if raw_value[0] in {'"', "'"} and raw_value[-1:] == raw_value[0]:
        return key, raw_value[1:-1]

    inline_comment_index = raw_value.find(" #")
    if inline_comment_index >= 0:
        raw_value = raw_value[:inline_comment_index].rstrip()
    return key, raw_value


def _load_dotenv_values(env_file: Path) -> dict[str, str]:
    try:
        content = env_file.read_text(encoding="utf-8")
    except OSError:
        return {}

    values: dict[str, str] = {}
    for line in content.splitlines():
        parsed = _parse_dotenv_assignment(line)
        if parsed is None:
            continue
        key, value = parsed
        values[key] = value
    return values


def _detect_provider_api_key(
    provider: str,
    *,
    search_roots: Sequence[Path] | None = None,
) -> tuple[str, str] | None:
    env_names = _provider_api_key_env_names(provider)
    for env_name in env_names:
        value = os.getenv(env_name, "").strip()
        if value:
            return value, f"environment variable {env_name}"

    roots = tuple(search_roots) if search_roots is not None else _provider_key_search_roots()
    for root in roots:
        for env_file_name in _ENV_FILE_NAMES:
            env_file = root / env_file_name
            if not env_file.is_file():
                continue
            env_values = _load_dotenv_values(env_file)
            for env_name in env_names:
                value = env_values.get(env_name, "").strip()
                if value:
                    return value, f"{env_file.name} ({env_name})"
    return None


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
        choices=LOG_LEVEL_CHOICES,
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


async def _resolve_enrichment_job_identity(
    provider_service: Any,
) -> tuple[str, str]:
    """Resolve the runtime provider/model pair for a new enrichment job."""

    provider_name, model_name, _worker_count = await _resolve_enrichment_job_plan(
        provider_service,
        row_count=1,
    )
    return provider_name, model_name


async def _resolve_enrichment_job_plan(
    provider_service: Any,
    *,
    row_count: int,
) -> tuple[str, str, int]:
    """Resolve provider/model plus bounded row concurrency for an enrichment job."""

    if provider_service is None or not hasattr(provider_service, "list_enabled_runtime_configs"):
        return "deterministic", "deterministic-parser", 1

    try:
        runtimes = await provider_service.list_enabled_runtime_configs()
    except Exception:  # pragma: no cover - defensive runtime lookup
        return "deterministic", "deterministic-parser", 1

    for runtime in runtimes:
        provider_name = str(getattr(runtime, "provider", "")).strip()
        model_name = str(getattr(runtime, "model", "")).strip()
        if not provider_name or not model_name:
            continue
        if bool(getattr(runtime, "manual_approval", False)):
            continue
        configured_workers = max(1, int(getattr(runtime, "max_concurrent", 1) or 1))
        tier_workers = _tier1_openai_worker_cap(provider_name, model_name)
        effective_workers = configured_workers
        if tier_workers > 0:
            effective_workers = max(effective_workers, tier_workers)
        return provider_name, model_name, min(max(1, row_count), effective_workers)

    return "deterministic", "deterministic-parser", 1


def _tier1_openai_worker_cap(provider_name: object, model_name: object) -> int:
    provider = str(provider_name or "").strip().lower()
    model = str(model_name or "").strip().lower()
    if provider != "openai":
        return 0
    limits = _OPENAI_TIER1_MODEL_LIMITS.get(model)
    if not limits:
        return 0
    rpm = int(limits.get("rpm", 0) or 0)
    tpm = int(limits.get("tpm", 0) or 0)
    if rpm <= 0 or tpm <= 0:
        return 0
    rpm_cap = max(1, (rpm * _ENRICHMENT_REQUEST_SECONDS) // 60)
    tpm_cap = max(1, tpm // _ENRICHMENT_REQUEST_TOKEN_BUDGET)
    return max(1, min(rpm_cap, tpm_cap))


def _resolve_llm_stage(
    provider_service: Any,
    provider_config_repository: Any | None = None,
) -> LLMStage | None:
    """Resolve an optional provider-backed grounded LLM enrichment stage."""

    candidate_names = (
        "build_llm_enrichment_stage",
        "create_llm_enrichment_stage",
        "get_llm_enrichment_stage",
        "resolve_llm_enrichment_stage",
        "llm_enrichment_stage",
    )
    for hook_name in candidate_names:
        hook = getattr(provider_service, hook_name, None)
        if hook is None or not callable(hook):
            continue
        try:
            signature = inspect.signature(hook)
        except (TypeError, ValueError):
            signature = None
        if signature is None:
            return hook(provider_service)

        positional_params = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        ]
        required_params = [
            parameter
            for parameter in positional_params
            if parameter.default is inspect.Signature.empty
        ]
        if len(required_params) >= 2:
            return hook(provider_service, provider_config_repository)
        if len(required_params) == 1:
            parameter_name = required_params[0].name.lower()
            if provider_config_repository is not None and any(
                token in parameter_name
                for token in ("repo", "config", "repository", "settings")
            ):
                return hook(provider_config_repository)
            return hook(provider_service)
        return hook()

    if not isinstance(provider_service, ProviderManagementService):
        return None

    async def grounded_llm_stage(
        row: BomRow,
        request: LLMEnrichmentRequest,
    ):
        last_outcome = None
        for runtime in await provider_service.list_enabled_runtime_configs():
            if runtime.manual_approval:
                continue
            stage = build_grounded_llm_enrichment_stage(
                provider_service.get_adapter(runtime.provider),
                api_key=runtime.api_key,
                model=runtime.model,
                timeout_seconds=runtime.timeout_seconds,
                temperature=runtime.temperature,
                reasoning_effort=runtime.reasoning_effort,
            )
            outcome = await stage(row, request)
            if outcome is None:
                continue
            if outcome.success:
                return outcome
            last_outcome = outcome
        return last_outcome

    return grounded_llm_stage


def _wire_phase6_import_flow(window: MainWindow) -> None:
    import_logger = logger.bind(flow="import")
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
        import_logger.info(
            "import_requested",
            source_count=len(source_paths),
            sources=[str(path) for path in source_paths],
        )
        try:
            window.set_progress(10)
            window.set_status_text("Analyzing column mappings...")
            preview = await import_use_case.build_preview(first_source)
            import_logger.debug(
                "import_preview_ready",
                source=str(first_source),
                detected_mappings=len(preview.column_mappings),
                unmapped_columns=list(preview.unmapped_columns),
                warnings=list(preview.warnings),
            )

            dialog = ColumnMappingDialog(
                detected_mappings=_mapping_dict(preview.column_mappings),
                unmapped_columns=list(preview.unmapped_columns),
                warnings=list(preview.warnings),
                parent=window,
            )
            if dialog.exec() != int(QDialog.DialogCode.Accepted):
                import_logger.info("import_cancelled", stage="column_mapping_dialog")
                window.set_status_text("Import cancelled")
                window.set_progress(0)
                return

            selected_mappings = _mapping_list(dialog.selected_mappings)
            if not selected_mappings:
                import_logger.warning("import_blocked_missing_mappings", source=str(first_source))
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
            state["project_name"] = project.name or first_source.stem
            state["rows"] = list(rows)
            state["project_id"] = int(project.id or 0)
            state["active_job_id"] = 0
            import_logger.info(
                "import_completed",
                project_id=state["project_id"],
                project_name=state["project_name"],
                row_count=report.imported_count,
                file_count=len(source_paths),
                warning_count=len(report.warnings),
                unmapped_columns=list(report.unmapped_columns),
            )

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
    provider_logger = logger.bind(flow="providers")
    provider_widget = window.page_widget("providers")
    providers_page = provider_widget if isinstance(provider_widget, ProvidersPage) else None
    if providers_page is None:
        return

    session_factory = getattr(window, "_phase6_session_factory", None)
    secret_store = KeyringSecretStore()
    provider_config_repository = (
        SqliteProviderConfigRepository(session_factory)
        if session_factory is not None
        else None
    )
    provider_service = ProviderManagementService(
        secret_store,
        config_repository=provider_config_repository,
    )
    provider_service.register_adapter(OpenAIProviderAdapter())
    provider_service.register_adapter(AnthropicProviderAdapter())

    capability_by_provider: dict[str, dict[str, object]] = {}
    for provider in provider_service.list_providers():
        capabilities = provider_service.get_capabilities(provider)
        provider_logger.debug(
            "provider_capabilities_loaded",
            provider=provider,
            supports_reasoning_control=capabilities.supports_reasoning_control,
            supports_model_discovery=capabilities.supports_model_discovery,
            reasoning_levels=list(capabilities.reasoning_levels),
        )
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

    def _normalize_reasoning_effort(value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized in {"low", "medium", "high"}:
            return normalized
        return ""

    def _parse_cached_models(payload: str) -> list[str]:
        text = payload.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip() for item in parsed if str(item).strip()]

    async def _load_provider_config(provider: str) -> ProviderConfig:
        stored = await provider_service.get_provider_config(provider)
        if stored is not None:
            return stored
        return ProviderConfig(provider_name=provider, enabled=True)

    async def initialize_provider_state() -> None:
        for provider in provider_service.list_providers():
            state = await provider_service.describe_provider(provider)
            config = await _load_provider_config(provider)
            detected_key = ""
            detected_source = ""
            detected = _detect_provider_api_key(provider)
            if detected is not None:
                detected_key, detected_source = detected
                providers_page.set_provider_api_key(provider, detected_key)
                await provider_service.store_provider_key(provider, detected_key)
                provider_logger.info(
                    "provider_api_key_detected",
                    provider=provider,
                    source=detected_source,
                )
            provider_logger.debug(
                "provider_state_initialized",
                provider=provider,
                has_stored_key=state.has_stored_key,
            )
            cached_models = _parse_cached_models(config.cached_models)
            selected_model = config.selected_model.strip()
            if cached_models:
                providers_page.set_provider_models(
                    provider,
                    cached_models,
                    selected_model=selected_model,
                )
            providers_page.set_provider_runtime_settings(
                provider,
                enabled=config.enabled,
                selected_model=selected_model,
                reasoning_mode=config.reasoning_effort or "Auto",
            )
            if detected_key:
                providers_page.set_connection_status_text(
                    provider,
                    f"API key detected from {detected_source} and applied",
                )
            elif state.has_stored_key:
                providers_page.set_connection_status_text(
                    provider,
                    "Stored key available",
                )
            else:
                providers_page.set_connection_status_text(
                    provider,
                    "No key stored",
                )

            if provider != "openai" or not detected_key:
                continue

            result = await provider_service.test_provider_connection(provider, detected_key)
            if not result.success:
                providers_page.set_connection_status_text(
                    provider,
                    (
                        f"API key detected from {detected_source} and applied, "
                        f"but validation failed: {result.message}"
                    ),
                )
                continue

            default_model = ""
            if not config.selected_model.strip():
                default_model = _provider_default_model(provider)
                if default_model:
                    selected_model = default_model
                    if default_model not in cached_models:
                        cached_models = [default_model, *cached_models]
                    providers_page.set_provider_models(
                        provider,
                        cached_models or [default_model],
                        selected_model=default_model,
                    )
                    providers_page.set_provider_runtime_settings(
                        provider,
                        enabled=config.enabled,
                        selected_model=default_model,
                        reasoning_mode=config.reasoning_effort or "Auto",
                    )

            if provider_config_repository is not None:
                await provider_service.save_provider_config(
                    provider,
                    {
                        "enabled": config.enabled,
                        "selected_model": selected_model,
                        "reasoning_mode": config.reasoning_effort or "Auto",
                        "available_models": cached_models or [selected_model],
                    },
                )
            if default_model and not config.selected_model.strip():
                providers_page.set_connection_status_text(
                    provider,
                    (
                        f"API key detected from {detected_source}, applied, and verified; "
                        f"default model set to {selected_model}"
                    ),
                )
            else:
                providers_page.set_connection_status_text(
                    provider,
                    f"API key detected from {detected_source}, applied, and verified",
                )
        if secret_store.status.available:
            provider_logger.info(
                "provider_keyring_ready",
                backend_name=secret_store.status.backend_name,
            )
            window.set_connection_state(
                f"Provider: keyring ready ({secret_store.status.backend_name})"
            )
        else:
            provider_logger.warning("provider_keyring_unavailable")
            window.set_connection_state("Provider: keyring unavailable")

    async def test_provider_connection(provider: str, api_key: str) -> None:
        key = api_key.strip()
        if not key:
            stored = await provider_service.retrieve_provider_key(provider)
            key = stored or ""

        if not key:
            provider_logger.warning("provider_test_blocked_missing_key", provider=provider)
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
        provider_logger.info("provider_connection_test_started", provider=provider)
        result = await provider_service.test_provider_connection(provider, key)
        if result.success:
            await provider_service.store_provider_key(provider, key)
            provider_logger.info(
                "provider_connection_test_succeeded",
                provider=provider,
                latency_ms=result.latency_ms,
            )
            providers_page.set_connection_status_text(
                provider,
                f"Connected ({int(result.latency_ms)} ms)",
            )
            window.set_connection_state(f"Provider: {provider} connected")
            return

        provider_logger.warning(
            "provider_connection_test_failed",
            provider=provider,
            message=result.message,
        )
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
            provider_logger.warning("provider_model_refresh_blocked_missing_key", provider=provider)
            providers_page.set_connection_status_text(provider, "Missing API key")
            return

        providers_page.set_connection_status_text(provider, "Refreshing models...")
        provider_logger.info("provider_model_refresh_started", provider=provider)
        models = await provider_service.discover_models(provider, key)
        model_ids = [model.id for model in models]
        providers_page.set_provider_models(
            provider,
            model_ids,
        )
        provider_logger.info(
            "provider_model_refresh_completed",
            provider=provider,
            model_count=len(models),
            models=model_ids,
        )
        if provider_config_repository is not None:
            config = await _load_provider_config(provider)
            selected_model = config.selected_model.strip()
            if not selected_model and model_ids:
                selected_model = model_ids[0]
            await provider_service.save_provider_config(
                provider,
                {
                    "enabled": config.enabled,
                    "selected_model": selected_model,
                    "reasoning_mode": config.reasoning_effort or "Auto",
                    "available_models": model_ids,
                },
            )
            providers_page.set_provider_runtime_settings(
                provider,
                enabled=config.enabled,
                selected_model=selected_model,
                reasoning_mode=config.reasoning_effort or "Auto",
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
            if provider_config_repository is not None:
                await provider_service.save_provider_config(provider, provider_payload)
            if api_key:
                await provider_service.store_provider_key(provider, api_key)
                saved += 1
            elif not bool(provider_payload.get("enabled", True)):
                await provider_service.delete_provider_key(provider)
                provider_logger.info("provider_key_deleted", provider=provider)
        provider_logger.info(
            "provider_settings_saved",
            providers=list(payload.keys()),
            stored_key_count=saved,
        )
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
    window._phase7_provider_config_repository = provider_config_repository  # type: ignore[attr-defined]
    window._phase7_secret_store = secret_store  # type: ignore[attr-defined]


def _wire_phase8_enrichment_flow(window: MainWindow) -> None:
    enrichment_logger = logger.bind(flow="enrichment")
    repository = getattr(window, "_phase6_repository", None)
    session_factory = getattr(window, "_phase6_session_factory", None)
    state = getattr(window, "_phase6_state", None)
    provider_service = getattr(window, "_phase7_provider_service", None)
    if not isinstance(repository, SqliteBomRepository):
        return
    if session_factory is None or not isinstance(state, dict):
        return

    bom_table_widget = window.page_widget("bom_table")
    jobs_widget = window.page_widget("jobs")
    bom_table_page = bom_table_widget if isinstance(bom_table_widget, BomTablePage) else None
    jobs_page = jobs_widget if isinstance(jobs_widget, JobsPage) else None

    llm_stage = _resolve_llm_stage(
        provider_service,
        getattr(window, "_phase7_provider_config_repository", None),
    )
    if llm_stage is None:
        enrichment_logger.debug("enrichment_llm_stage_unavailable")
    else:
        enrichment_logger.debug("enrichment_llm_stage_resolved")

    enrichment_use_case = BomEnrichmentUseCase(
        repository,
        LcscEvidenceRetriever(),
        llm_stage=llm_stage,
    )
    job_repository = SqliteJobRepository(session_factory=session_factory)
    job_event_bus = EventBus[object]()
    job_manager = JobManager(job_repository, event_bus=job_event_bus, max_concurrency=3)

    async def refresh_project_rows() -> list[BomRow]:
        project_id = int(state.get("project_id", 0) or 0)
        if project_id <= 0:
            return []

        rows = await repository.list_rows_by_project(project_id)
        enrichment_logger.debug(
            "enrichment_project_rows_refreshed",
            project_id=project_id,
            row_count=len(rows),
        )
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

        provider_name, model_name, row_concurrency = await _resolve_enrichment_job_plan(
            provider_service,
            row_count=len(normalized_ids),
        )
        job = Job(
            job_type="enrichment",
            state="pending",
            project_id=project_id,
            target_row_ids=",".join(str(row_id) for row_id in normalized_ids),
            total_rows=len(normalized_ids),
            provider_name=provider_name,
            model_name=model_name,
        )

        async def executor(row_id: int) -> bool:
            result = await enrichment_use_case.enrich_row_with_result(row_id)
            if not isinstance(result, EnrichmentExecutionResult):
                return bool(result)
            return RowExecutionResult(
                success=result.success,
                latency_ms=result.telemetry.latency_ms,
                usage=dict(result.telemetry.usage),
                error_category=result.telemetry.error_category,
                rate_limited=result.telemetry.rate_limited,
                retry_after_seconds=result.telemetry.retry_after_seconds,
            )

        persisted = await job_manager.submit(
            job,
            executor,
            row_concurrency=row_concurrency,
        )
        state["active_job_id"] = int(persisted.id or 0)
        enrichment_logger.info(
            "enrichment_job_queued",
            job_id=state["active_job_id"],
            project_id=project_id,
            row_count=len(normalized_ids),
            row_ids=normalized_ids,
            provider_name=provider_name,
            model_name=model_name,
            row_concurrency=row_concurrency,
        )
        window.show_page("jobs")
        window.set_progress(0)
        window.set_status_text(
            f"Queued enrichment job {persisted.id} ({len(normalized_ids)} rows, {row_concurrency} workers)"
        )
        if jobs_page is not None:
            jobs_page.upsert_job(persisted)

    async def on_job_event(event: object) -> None:
        if isinstance(event, JobQueued):
            enrichment_logger.info("job_event_queued", job_id=event.job_id)
            if jobs_page is not None:
                saved = await job_repository.get(event.job_id)
                if saved is not None:
                    jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} queued")
            return

        if isinstance(event, JobStarted):
            enrichment_logger.info("job_event_started", job_id=event.job_id)
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
                enrichment_logger.debug(
                    "job_event_progress",
                    job_id=event.job_id,
                    processed=processed,
                    total_rows=saved.total_rows,
                    completed_rows=saved.completed_rows,
                    failed_rows=saved.failed_rows,
                    progress=progress,
                )
                window.set_status_text(
                    f"Job {event.job_id}: {processed}/{saved.total_rows} rows processed"
                )
            return

        if isinstance(event, JobCompleted):
            enrichment_logger.info(
                "job_event_completed",
                job_id=event.job_id,
                completed_rows=event.completed_rows,
                failed_rows=event.failed_rows,
            )
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
            enrichment_logger.error(
                "job_event_failed",
                job_id=event.job_id,
                error_message=event.error_message,
            )
            saved = await job_repository.get(event.job_id)
            if saved is not None and jobs_page is not None:
                jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} failed: {event.error_message}")
            return

        if isinstance(event, JobCancelled):
            enrichment_logger.warning("job_event_cancelled", job_id=event.job_id)
            saved = await job_repository.get(event.job_id)
            if saved is not None and jobs_page is not None:
                jobs_page.upsert_job(saved)
            window.set_status_text(f"Job {event.job_id} cancelled")
            return

        if isinstance(event, JobPaused):
            enrichment_logger.info("job_event_paused", job_id=event.job_id)
            window.set_status_text(f"Job {event.job_id} paused")
            return

        if isinstance(event, JobResumed):
            enrichment_logger.info("job_event_resumed", job_id=event.job_id)
            window.set_status_text(f"Job {event.job_id} resumed")

    job_event_bus.subscribe(on_job_event)

    async def enrich_selected() -> None:
        row_ids = selected_row_ids()
        if not row_ids:
            row_id = selected_row_id()
            if row_id is not None:
                row_ids = [row_id]
        if not row_ids:
            window.set_status_text("Select a row to enrich")
            return
        await submit_enrichment_job(row_ids)

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
    part_finder_logger = logger.bind(flow="part_finder")
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

    def _criteria_filters(criteria: Mapping[str, Any] | None = None) -> dict[str, bool]:
        if criteria is not None:
            payload = criteria.get("filters")
            if isinstance(payload, Mapping):
                return {
                    "active_only": bool(payload.get("active_only", False)),
                    "in_stock": bool(payload.get("in_stock", False)),
                    "lcsc_available": bool(payload.get("lcsc_available", False)),
                }
        return part_finder_page.current_filters()

    def _candidate_source_row_id(candidate_row: Mapping[str, Any]) -> int | None:
        value = candidate_row.get("source_row_id")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def _candidate_target_row_ids(candidate_row: Mapping[str, Any]) -> list[int]:
        payload = candidate_row.get("target_row_ids")
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            source_row_id = _candidate_source_row_id(candidate_row)
            return [source_row_id] if source_row_id is not None else []
        row_ids: list[int] = []
        for value in payload:
            if isinstance(value, int) and value > 0 and value not in row_ids:
                row_ids.append(value)
            elif isinstance(value, str) and value.isdigit():
                parsed = int(value)
                if parsed > 0 and parsed not in row_ids:
                    row_ids.append(parsed)
        return row_ids

    def _selected_row_payloads() -> list[dict[str, Any]]:
        payloads = state.get("selected_row_payloads")
        if isinstance(payloads, list):
            normalized: list[dict[str, Any]] = []
            for payload in payloads:
                if isinstance(payload, Mapping):
                    normalized.append(dict(payload))
            return normalized
        if bom_table_page is None:
            return []
        return [dict(payload) for payload in bom_table_page.selected_row_payloads()]

    def _state_rows() -> list[BomRow]:
        rows = state.get("rows", [])
        return [row for row in rows if isinstance(row, BomRow)]

    def _normalize_row_id(value: object) -> int | None:
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            parsed = int(value)
            return parsed if parsed > 0 else None
        return None

    def _row_shortage_reason(row: BomRow, scope: str) -> str:
        stock_status = str(row.stock_status or "").strip().lower()
        stock_qty = row.stock_qty
        quantity = int(row.quantity or 0)
        lifecycle = str(row.lifecycle_status or "").strip().lower()
        if scope == "no_availability":
            if stock_qty == 0:
                return "Stock quantity is 0."
            if stock_status in {"out", "unavailable", "out_of_stock"}:
                return f"Stock status is {stock_status or 'unavailable'}."
            return "No supplier availability was confirmed."
        if scope == "insufficient_stock":
            return f"Available stock ({stock_qty or 0}) is below required quantity ({quantity})."
        if scope == "lifecycle_risk":
            return f"Lifecycle status is {lifecycle or 'unknown'}."
        return "Selected for bulk replacement review."

    def _bulk_scope_rows(scope: str) -> list[BomRow]:
        rows = _state_rows()
        if scope == "selected_rows":
            selected_ids = {
                row_id
                for row_id in (_normalize_row_id(payload.get("id")) for payload in _selected_row_payloads())
                if row_id is not None
            }
            return [row for row in rows if int(row.id or 0) in selected_ids]
        if scope == "no_availability":
            return [
                row
                for row in rows
                if (
                    row.stock_qty == 0
                    or str(row.stock_status or "").strip().lower() in {"out", "unavailable", "out_of_stock"}
                )
            ]
        if scope == "insufficient_stock":
            return [
                row
                for row in rows
                if row.stock_qty is not None and int(row.quantity or 0) > 0 and row.stock_qty < int(row.quantity or 0)
            ]
        if scope == "lifecycle_risk":
            return [
                row
                for row in rows
                if str(row.lifecycle_status or "").strip().lower() in {"nrnd", "last_time_buy", "eol"}
            ]
        return []

    def _bulk_target_payloads(rows: Sequence[BomRow], *, scope: str) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for row in rows:
            payloads.append(
                {
                    "id": int(row.id or 0),
                    "designator": row.designator,
                    "mpn": row.mpn or row.lcsc_part_number,
                    "footprint": row.footprint,
                    "quantity": row.quantity,
                    "stock": row.stock_qty if row.stock_qty is not None else row.stock_status,
                    "reason": _row_shortage_reason(row, scope),
                }
            )
        return payloads

    def selected_row_ids() -> list[int]:
        if bom_table_page is None:
            return []
        row_ids: list[int] = []
        for payload in bom_table_page.selected_row_payloads():
            value = payload.get("id")
            if isinstance(value, int) and value > 0 and value not in row_ids:
                row_ids.append(value)
            elif isinstance(value, str) and value.isdigit():
                parsed = int(value)
                if parsed > 0 and parsed not in row_ids:
                    row_ids.append(parsed)
        return row_ids

    def _replacement_rows_payload(
        results: Sequence[Any],
        *,
        source_row_id: int | None,
        target_row_ids: Sequence[int] | None = None,
        targets_label: str = "",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        normalized_target_row_ids = [int(row_id) for row_id in (target_row_ids or []) if int(row_id) > 0]
        resolved_targets_label = targets_label or (
            f"{len(normalized_target_row_ids)} row(s)"
            if normalized_target_row_ids
            else "1 row"
        )
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
                    "targets": resolved_targets_label,
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
                    "source_row_id": source_row_id,
                    "target_row_ids": normalized_target_row_ids or ([source_row_id] if source_row_id is not None else []),
                }
            )
        return rows

    async def _search_from_selected() -> None:
        if part_finder_page.is_busy():
            part_finder_page.set_status_message("Search already in progress.")
            return
        row_id = _context_row_id()
        if row_id is None:
            part_finder_page.set_status_message("Select a BOM row before searching.")
            return

        filters = _criteria_filters()
        part_finder_page.set_busy_state(searching=True)
        try:
            part_finder_page.set_status_message("Searching candidates from selected row...")
            part_finder_logger.info(
                "replacement_search_started",
                mode="selected_row",
                row_id=row_id,
                filters=filters,
            )
            results = await find_parts_use_case.find_candidates(
                row_id=row_id,
                criteria=PartSearchCriteria(
                    active_only=filters["active_only"],
                    in_stock=filters["in_stock"],
                    lcsc_available=filters["lcsc_available"],
                ),
            )
            payload = _replacement_rows_payload(results, source_row_id=row_id)
            part_finder_page.set_candidates(payload)
            if not results:
                part_finder_logger.info(
                    "replacement_search_no_results",
                    mode="selected_row",
                    row_id=row_id,
                    filters=filters,
                )
                part_finder_page.set_status_message("No replacement candidates found.")
                return

            needs_review = sum(1 for result in results if result.requires_manual_review)
            part_finder_logger.info(
                "replacement_search_completed",
                mode="selected_row",
                row_id=row_id,
                result_count=len(results),
                manual_review_count=needs_review,
                filters=filters,
            )
            part_finder_page.set_status_message(
                f"Found {len(results)} candidates ({needs_review} need manual review)."
            )
        except Exception as exc:
            part_finder_logger.exception(
                "replacement_search_failed",
                mode="selected_row",
                row_id=row_id,
                error=str(exc),
                filters=filters,
            )
            part_finder_page.clear_candidates()
            part_finder_page.set_status_message(f"Search failed: {exc}")
        finally:
            part_finder_page.set_busy_state(searching=False)

    async def _search_with_criteria(criteria: Mapping[str, Any]) -> None:
        if part_finder_page.is_busy():
            part_finder_page.set_status_message("Search already in progress.")
            return
        context_row_id = _context_row_id(criteria)
        filters = _criteria_filters(criteria)
        part_finder_page.set_busy_state(searching=True)
        try:
            part_finder_page.set_status_message("Searching candidates...")
            part_finder_logger.info(
                "replacement_search_started",
                mode="manual_criteria",
                row_id=context_row_id,
                criteria=dict(criteria),
            )
            results = await find_parts_use_case.find_candidates(
                row_id=context_row_id,
                criteria=PartSearchCriteria(
                    part_number=str(criteria.get("part_number", "")).strip(),
                    footprint=str(criteria.get("footprint", "")).strip(),
                    value=str(criteria.get("value", "")).strip(),
                    manufacturer=str(criteria.get("manufacturer", "")).strip(),
                    active_only=filters["active_only"],
                    in_stock=filters["in_stock"],
                    lcsc_available=filters["lcsc_available"],
                ),
            )
            payload = _replacement_rows_payload(results, source_row_id=context_row_id)
            part_finder_page.set_candidates(payload)
            if not results:
                part_finder_logger.info(
                    "replacement_search_no_results",
                    mode="manual_criteria",
                    row_id=context_row_id,
                    filters=filters,
                )
                part_finder_page.set_status_message("No replacement candidates found.")
                return
            part_finder_logger.info(
                "replacement_search_completed",
                mode="manual_criteria",
                row_id=context_row_id,
                result_count=len(results),
                filters=filters,
            )
            part_finder_page.set_status_message(f"Found {len(results)} candidates.")
        except Exception as exc:
            part_finder_logger.exception(
                "replacement_search_failed",
                mode="manual_criteria",
                row_id=context_row_id,
                error=str(exc),
                criteria=dict(criteria),
            )
            part_finder_page.clear_candidates()
            part_finder_page.set_status_message(f"Search failed: {exc}")
        finally:
            part_finder_page.set_busy_state(searching=False)

    async def _search_bulk(scope_payload: Mapping[str, Any]) -> None:
        if part_finder_page.is_busy():
            part_finder_page.set_status_message("Search already in progress.")
            return

        scope = str(scope_payload.get("scope", "selected_rows")).strip() or "selected_rows"
        filters = _criteria_filters(scope_payload)
        target_rows = _bulk_scope_rows(scope)
        part_finder_page.set_bulk_targets(
            _bulk_target_payloads(target_rows, scope=scope),
            scope_label=part_finder_page.bulk_scope_combo.currentText(),
        )
        if not target_rows:
            part_finder_page.clear_candidates()
            part_finder_page.set_status_message("No target rows matched the selected bulk scope.")
            return

        batches = find_parts_use_case.build_replacement_batches(target_rows)
        part_finder_page.set_busy_state(searching=True)
        try:
            part_finder_page.set_status_message("Searching grouped replacement candidates...")
            part_finder_logger.info(
                "replacement_search_started",
                mode="bulk_scope",
                scope=scope,
                batch_count=len(batches),
                target_count=len(target_rows),
                filters=filters,
            )
            candidate_rows: list[dict[str, Any]] = []
            for batch in batches:
                results = await find_parts_use_case.find_candidates(
                    row_id=batch.exemplar_row_id,
                    criteria=PartSearchCriteria(
                        active_only=filters["active_only"],
                        in_stock=filters["in_stock"],
                        lcsc_available=filters["lcsc_available"],
                    ),
                )
                candidate_rows.extend(
                    _replacement_rows_payload(
                        results,
                        source_row_id=batch.exemplar_row_id,
                        target_row_ids=list(batch.row_ids),
                        targets_label=f"{len(batch.row_ids)} row(s): {', '.join(batch.designators[:3])}"
                        + ("..." if len(batch.designators) > 3 else ""),
                    )
                )

            candidate_rows.sort(
                key=lambda row: (
                    -len(_candidate_target_row_ids(row)),
                    -float(row.get("match_score", 0.0) or 0.0),
                )
            )
            part_finder_page.set_candidates(candidate_rows)
            if not candidate_rows:
                part_finder_logger.info(
                    "replacement_search_no_results",
                    mode="bulk_scope",
                    scope=scope,
                    target_count=len(target_rows),
                    filters=filters,
                )
                part_finder_page.set_status_message("No grouped replacement candidates found.")
                return

            part_finder_logger.info(
                "replacement_search_completed",
                mode="bulk_scope",
                scope=scope,
                target_count=len(target_rows),
                batch_count=len(batches),
                result_count=len(candidate_rows),
                filters=filters,
            )
            part_finder_page.set_status_message(
                f"Found {len(candidate_rows)} grouped candidates across {len(batches)} batch(es)."
            )
        except Exception as exc:
            part_finder_logger.exception(
                "replacement_search_failed",
                mode="bulk_scope",
                scope=scope,
                error=str(exc),
                filters=filters,
            )
            part_finder_page.clear_candidates()
            part_finder_page.set_status_message(f"Search failed: {exc}")
        finally:
            part_finder_page.set_busy_state(searching=False)

    async def _apply_candidate(candidate_row: Mapping[str, Any]) -> None:
        if part_finder_page.is_busy():
            part_finder_page.set_status_message("Find Parts is busy. Please wait.")
            return
        target_row_ids = _candidate_target_row_ids(candidate_row)
        row_id = target_row_ids[0] if target_row_ids else _context_row_id()
        if row_id is None or not target_row_ids:
            part_finder_page.set_status_message("No target BOM rows to apply replacement.")
            return
        candidate_source_row_id = _candidate_source_row_id(candidate_row)
        if len(target_row_ids) == 1 and candidate_source_row_id is not None and candidate_source_row_id != row_id:
            part_finder_logger.warning(
                "replacement_apply_stale_candidate_blocked",
                selected_row_id=row_id,
                candidate_source_row_id=candidate_source_row_id,
            )
            part_finder_page.set_status_message(
                "Candidate results belong to a different BOM row. Re-run search."
            )
            return

        candidate_payload = candidate_row.get("candidate_payload")
        if not isinstance(candidate_payload, Mapping):
            part_finder_page.set_status_message("Invalid candidate payload.")
            return

        candidate_name = _candidate_display_name(candidate_row)
        target_count = len(target_row_ids)
        confirmation_message = (
            f"Apply replacement '{candidate_name}' to {target_count} BOM row(s)?\n\n"
            "This action updates the row(s) and marks replacement as user accepted."
            if target_count > 1
            else (
                f"Apply replacement '{candidate_name}' to selected BOM row?\n\n"
                "This action updates the row and marks replacement as user accepted."
            )
        )
        confirm = QMessageBox.question(
            window,
            "Confirm Replacement",
            confirmation_message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            part_finder_logger.info(
                "replacement_apply_cancelled",
                row_ids=target_row_ids,
                candidate_name=candidate_name,
            )
            part_finder_page.set_status_message("Replacement cancelled.")
            return

        part_finder_page.set_busy_state(applying=True)
        try:
            results = await find_parts_use_case.apply_replacement_to_rows(
                target_row_ids,
                dict(candidate_payload),
                confirmed=True,
            )
        except ReplacementConfirmationRequired:
            part_finder_page.set_status_message("Replacement requires explicit confirmation.")
            return
        except Exception as exc:
            logger.exception("replacement_apply_failed", error=str(exc), row_ids=target_row_ids)
            part_finder_page.set_status_message(f"Failed to apply replacement: {exc}")
            return
        finally:
            part_finder_page.set_busy_state(applying=False)

        await _refresh_project_rows()
        part_finder_logger.info(
            "replacement_applied",
            row_ids=target_row_ids,
            candidate_name=candidate_name,
            candidate_mpn=results[0].candidate.mpn if results else "",
            candidate_lcsc_part_number=results[0].candidate.lcsc_part_number if results else "",
        )
        part_finder_page.set_status_message(
            f"Applied replacement to {len(target_row_ids)} row(s): "
            f"{(results[0].candidate.mpn or results[0].candidate.lcsc_part_number) if results else candidate_name}."
        )
        window.set_status_text(
            f"Replacement applied to {len(target_row_ids)} row(s)"
        )

    def _on_table_row_selected(row_payload: dict[str, Any]) -> None:
        previous_row_id = _context_row_id()
        if row_payload:
            state["selected_row_payload"] = dict(row_payload)
            part_finder_page.set_context_row(row_payload)
            new_row_id = _context_row_id()
            if previous_row_id != new_row_id:
                part_finder_page.clear_candidates()
                part_finder_page.set_status_message(
                    "BOM row context changed. Re-run search for replacements."
                )
        else:
            state["selected_row_payload"] = None
            part_finder_page.set_context_row(None)
            part_finder_page.clear_candidates()

    def _on_table_selection_changed(payloads: list[dict[str, Any]]) -> None:
        state["selected_row_payloads"] = [dict(payload) for payload in payloads if isinstance(payload, Mapping)]
        if part_finder_page.current_mode() == "bulk" and part_finder_page.current_bulk_scope() == "selected_rows":
            selected_rows = _bulk_scope_rows("selected_rows")
            part_finder_page.set_bulk_targets(
                _bulk_target_payloads(selected_rows, scope="selected_rows"),
                scope_label="Selected BOM rows",
            )
            part_finder_page.clear_candidates()
            if selected_rows:
                part_finder_page.set_status_message(
                    "BOM selection changed. Re-run bulk search for updated rows."
                )

    part_finder_page.search_from_selected_requested.connect(
        lambda: _schedule_async(_search_from_selected())
    )
    part_finder_page.search_requested.connect(
        lambda criteria: _schedule_async(_search_with_criteria(criteria))
    )
    part_finder_page.bulk_search_requested.connect(
        lambda payload: _schedule_async(_search_bulk(payload))
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
        bom_table_page.selection_changed.connect(_on_table_selection_changed)

    window._phase9_find_parts_use_case = find_parts_use_case  # type: ignore[attr-defined]


def _wire_phase10_export_flow(window: MainWindow) -> None:
    export_logger = logger.bind(flow="export")
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
        export_logger.info(
            "export_started",
            target=target,
            output_path=str(output_path),
            row_count=len(rows),
            filtered_column_count=len(filtered_columns or []),
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
        export_logger.info(
            "export_completed",
            target=target,
            output_path=str(result.output_path),
            rows_exported=result.rows_exported,
            sheets_created=list(result.sheets_created),
            warning_count=len(result.warnings),
            file_size_bytes=result.file_size_bytes,
            duration_seconds=result.duration_seconds,
        )
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
