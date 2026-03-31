"""Application use cases for exporting BOM data."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.ports import ExportOptions, ExportResult, IExporter

ExportTarget = Literal[
    "procurement_bom",
    "jlcpcb_assembly_bom",
    "full_table",
    "filtered_view",
    "current_filtered_view",
]

__all__ = [
    "ExportBomUseCase",
    "ExportTarget",
]


class ExportBomUseCase:
    """Coordinate export target selection and validation."""

    _target_aliases: dict[str, str] = {
        "procurement_bom": "procurement_bom",
        "jlcpcb_assembly_bom": "jlcpcb_assembly_bom",
        "full_table": "full_table",
        "filtered_view": "filtered_view",
        "current_filtered_view": "filtered_view",
    }
    _supported_targets: frozenset[str] = frozenset(_target_aliases.keys())

    def __init__(self, exporter: IExporter) -> None:
        self._exporter = exporter

    async def export(
        self,
        rows: Sequence[BomRow],
        output_path: str | Path,
        options: ExportOptions | None = None,
        *,
        target: ExportTarget | str = "procurement_bom",
        filtered_columns: Sequence[str] | None = None,
    ) -> ExportResult:
        """Export rows using the selected target."""

        normalized_target = self._normalize_target(target)
        export_options = options or ExportOptions()
        output = Path(output_path)
        row_list = list(rows)

        if normalized_target == "procurement_bom":
            return await self._exporter.export_procurement_bom(
                row_list,
                output,
                export_options,
            )
        if normalized_target == "jlcpcb_assembly_bom":
            return await self._exporter.export_jlcpcb_assembly_bom(
                row_list,
                output,
                export_options,
            )
        if normalized_target == "full_table":
            return await self._exporter.export_full_table(
                row_list,
                output,
                export_options,
            )

        columns = self._normalize_columns(filtered_columns)
        return await self._exporter.export_filtered_view(
            row_list,
            columns,
            output,
            export_options,
        )

    async def export_procurement_bom(
        self,
        rows: Sequence[BomRow],
        output_path: str | Path,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        return await self.export(
            rows,
            output_path,
            options,
            target="procurement_bom",
        )

    async def export_full_table(
        self,
        rows: Sequence[BomRow],
        output_path: str | Path,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        return await self.export(rows, output_path, options, target="full_table")

    async def export_filtered_view(
        self,
        rows: Sequence[BomRow],
        columns: Sequence[str],
        output_path: str | Path,
        options: ExportOptions | None = None,
    ) -> ExportResult:
        return await self.export(
            rows,
            output_path,
            options,
            target="filtered_view",
            filtered_columns=columns,
        )

    def _normalize_target(self, target: ExportTarget | str) -> str:
        value = str(target).strip().lower()
        if value not in self._supported_targets:
            raise ValueError(
                f"Unsupported export target '{target}'. "
                f"Expected one of: {', '.join(sorted(self._supported_targets))}."
            )
        return self._target_aliases[value]

    def _normalize_columns(self, columns: Sequence[str] | None) -> list[str]:
        normalized = [str(column).strip() for column in columns or [] if str(column).strip()]
        if not normalized:
            raise ValueError("filtered_view export requires at least one column name.")
        return normalized
