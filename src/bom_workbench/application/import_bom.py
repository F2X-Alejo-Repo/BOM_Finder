"""Deterministic BOM import orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..domain import ColumnMapping, ImportReport, ValidationWarning
from ..domain.entities import BomProject, BomRow
from ..domain.ports import IBomRepository
from ..infrastructure.csv import CsvParser, ParseResult
from ..infrastructure.csv.column_matcher import ColumnMatcher
from ..infrastructure.csv.normalizer import NormalizationResult, RowNormalizer
from .event_bus import (
    EventBus,
    ImportCompleted,
    ImportFailed,
    ImportPreviewReady,
    ImportStarted,
)

__all__ = [
    "ImportBomUseCase",
    "ImportPreview",
    "ImportResult",
]


class ImportPreview(BaseModel):
    """Deterministic preview payload for UI flows."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    source_file: str
    project_name: str
    encoding: str
    delimiter: str
    row_count: int
    headers: list[str] = Field(default_factory=list)
    column_mappings: list[ColumnMapping] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    validation_warnings: list[ValidationWarning] = Field(default_factory=list)
    preview_rows: list[BomRow] = Field(default_factory=list)
    report: ImportReport


class ImportResult(BaseModel):
    """Final import outcome after persistence."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    project: BomProject
    preview: ImportPreview
    imported_rows: list[BomRow] = Field(default_factory=list)
    report: ImportReport


class ImportBomUseCase:
    """Orchestrates BOM import from parse through persistence."""

    def __init__(
        self,
        repository: IBomRepository,
        *,
        parser: CsvParser | None = None,
        matcher: ColumnMatcher | None = None,
        normalizer: RowNormalizer | None = None,
        event_bus: EventBus[Any] | None = None,
    ) -> None:
        self._repository = repository
        self._parser = parser or CsvParser()
        self._matcher = matcher or ColumnMatcher()
        self._normalizer = normalizer or RowNormalizer()
        self._event_bus = event_bus

    async def preview_file(self, path: str | Path, project_name: str | None = None) -> ImportPreview:
        """Parse, match, and normalize a file without persisting anything."""

        source_path = Path(path)
        resolved_project_name = self._resolve_project_name(source_path, project_name)
        try:
            parsed = self._parser.parse(source_path)
            preview = await self._build_preview(parsed, source_path, resolved_project_name)
            await self._publish_preview_ready(preview)
            return preview
        except Exception as exc:
            await self._publish_failed(str(source_path), resolved_project_name, exc)
            raise

    async def build_preview(
        self,
        path: str | Path,
        project_name: str | None = None,
    ) -> ImportPreview:
        """Compatibility alias used by the app wiring."""

        return await self.preview_file(path, project_name=project_name)

    async def import_preview(
        self,
        preview: ImportPreview,
        project_name: str | None = None,
    ) -> ImportResult:
        """Persist a previously generated preview."""

        resolved_project_name = self._resolve_project_name(
            Path(preview.source_file),
            project_name or preview.project_name,
        )
        await self._publish_started(preview.source_file, resolved_project_name)

        try:
            project = BomProject(
                name=resolved_project_name,
                description=f"Imported from {Path(preview.source_file).name}",
                source_files=preview.source_file,
            )
            saved_project = await self._repository.save_project(project)
            project_id = self._require_project_id(saved_project)

            imported_rows: list[BomRow] = []
            for row in preview.preview_rows:
                row.project_id = project_id
                saved_row = await self._repository.save_row(row)
                imported_rows.append(saved_row)

            report = preview.report.model_copy(
                update={
                    "imported_count": len(imported_rows),
                    "warning_count": len(preview.warnings) + len(preview.validation_warnings),
                }
            )
            result = ImportResult(
                project=saved_project,
                preview=preview,
                imported_rows=imported_rows,
                report=report,
            )
            await self._publish_completed(
                preview.source_file,
                resolved_project_name,
                project_id,
                len(imported_rows),
            )
            return result
        except Exception as exc:
            await self._publish_failed(preview.source_file, resolved_project_name, exc)
            raise

    async def import_file(
        self,
        path: str | Path,
        project_name: str | None = None,
    ) -> ImportResult:
        """Convenience helper that previews and then persists a file."""

        preview = await self.preview_file(path, project_name=project_name)
        return await self.import_preview(preview, project_name=project_name)

    async def import_files(
        self,
        paths: Sequence[str | Path],
        *,
        mappings: Sequence[ColumnMapping],
        project_name: str | None = None,
    ) -> tuple[BomProject, ImportReport, list[BomRow]]:
        """Import multiple files into one project using explicit column mappings."""

        resolved_paths = [Path(path) for path in paths]
        if not resolved_paths:
            raise ValueError("At least one source path is required.")

        source_file = str(resolved_paths[0])
        resolved_project_name = self._resolve_project_name(
            resolved_paths[0],
            project_name,
        )
        await self._publish_started(source_file, resolved_project_name)

        try:
            project = BomProject(
                name=resolved_project_name,
                description=(
                    f"Imported from {len(resolved_paths)} file(s)"
                    if len(resolved_paths) > 1
                    else f"Imported from {resolved_paths[0].name}"
                ),
                source_files="; ".join(str(path) for path in resolved_paths),
            )
            saved_project = await self._repository.save_project(project)
            project_id = self._require_project_id(saved_project)

            imported_rows: list[BomRow] = []
            warnings: list[str] = []
            unmapped_columns: list[str] = []
            total_rows = 0
            mapped_raw_columns = {mapping.raw_column for mapping in mappings}

            for source_path in resolved_paths:
                parsed = self._parser.parse(source_path)
                total_rows += parsed.row_count
                unmapped_columns.extend(
                    header
                    for header in parsed.headers
                    if header not in mapped_raw_columns and header not in unmapped_columns
                )

                normalized = self._normalizer.normalize(
                    parsed.rows,
                    mappings,
                    source_file=str(source_path),
                    project_id=project_id,
                )
                warnings.extend(parsed.parse_warnings)
                warnings.extend(warning.message for warning in normalized.warnings)

                for row in normalized.rows:
                    row.project_id = project_id
                    saved_row = await self._repository.save_row(row)
                    imported_rows.append(saved_row)

            report = ImportReport(
                source_file=source_file,
                row_count=total_rows,
                imported_count=len(imported_rows),
                warning_count=len(warnings),
                error_count=0,
                unmapped_columns=unmapped_columns,
                warnings=warnings,
            )

            await self._publish_completed(
                source_file,
                resolved_project_name,
                project_id,
                len(imported_rows),
            )
            return saved_project, report, imported_rows
        except Exception as exc:
            await self._publish_failed(source_file, resolved_project_name, exc)
            raise

    async def _build_preview(
        self,
        parsed: ParseResult,
        source_path: Path,
        project_name: str,
    ) -> ImportPreview:
        mappings, unmapped_columns, match_warnings = self._matcher.match_headers(parsed.headers)
        normalization: NormalizationResult = self._normalizer.normalize(
            parsed.rows,
            mappings,
            source_file=str(source_path),
            project_id=0,
        )

        warnings = [*parsed.parse_warnings, *match_warnings]
        validation_warnings = list(normalization.warnings)
        warnings.extend(warning.message for warning in validation_warnings)

        report = ImportReport(
            source_file=str(source_path),
            row_count=parsed.row_count,
            imported_count=0,
            warning_count=len(warnings),
            error_count=0,
            unmapped_columns=list(unmapped_columns),
            warnings=list(warnings),
        )

        return ImportPreview(
            source_file=str(source_path),
            project_name=project_name,
            encoding=parsed.encoding,
            delimiter=parsed.delimiter,
            row_count=parsed.row_count,
            headers=list(parsed.headers),
            column_mappings=list(mappings),
            unmapped_columns=list(unmapped_columns),
            warnings=warnings,
            validation_warnings=validation_warnings,
            preview_rows=list(normalization.rows),
            report=report,
        )

    async def _publish_preview_ready(self, preview: ImportPreview) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            ImportPreviewReady(
                source_file=preview.source_file,
                project_name=preview.project_name,
                row_count=preview.row_count,
                warning_count=preview.report.warning_count,
            )
        )

    async def _publish_started(self, source_file: str, project_name: str) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            ImportStarted(
                source_file=source_file,
                project_name=project_name,
            )
        )

    async def _publish_completed(
        self,
        source_file: str,
        project_name: str,
        project_id: int,
        imported_count: int,
    ) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            ImportCompleted(
                source_file=source_file,
                project_name=project_name,
                project_id=project_id,
                imported_count=imported_count,
            )
        )

    async def _publish_failed(
        self,
        source_file: str,
        project_name: str,
        error: Exception,
    ) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            ImportFailed(
                source_file=source_file,
                project_name=project_name,
                error_message=str(error),
            )
        )

    def _resolve_project_name(self, source_path: Path, project_name: str | None) -> str:
        name = (project_name or source_path.stem).strip()
        return name or source_path.stem or "imported_bom"

    def _require_project_id(self, project: BomProject) -> int:
        if project.id is None:
            raise RuntimeError("Saved project did not return an id.")
        return project.id
