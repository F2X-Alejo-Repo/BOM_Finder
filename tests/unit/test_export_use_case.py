"""Unit tests for export orchestration target routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from bom_workbench.application import ExportBomUseCase
from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.ports import ExportOptions, ExportResult


class _FakeExporter:
    def __init__(self) -> None:
        self.called: dict[str, object] = {}

    async def export_procurement_bom(
        self,
        rows,
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult:
        self.called = {
            "method": "procurement",
            "rows": list(rows),
            "output_path": output_path,
            "options": options,
        }
        return ExportResult(output_path=str(output_path), rows_exported=len(list(rows)))

    async def export_full_table(
        self,
        rows,
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult:
        self.called = {
            "method": "full_table",
            "rows": list(rows),
            "output_path": output_path,
            "options": options,
        }
        return ExportResult(output_path=str(output_path), rows_exported=len(list(rows)))

    async def export_filtered_view(
        self,
        rows,
        columns,
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult:
        self.called = {
            "method": "filtered_view",
            "rows": list(rows),
            "columns": list(columns),
            "output_path": output_path,
            "options": options,
        }
        return ExportResult(output_path=str(output_path), rows_exported=len(list(rows)))


@pytest.mark.anyio
async def test_export_use_case_accepts_current_filtered_view_alias(tmp_path: Path) -> None:
    rows = [BomRow(project_id=1, designator="R1")]
    exporter = _FakeExporter()
    use_case = ExportBomUseCase(exporter)

    result = await use_case.export(
        rows,
        tmp_path / "filtered.xlsx",
        ExportOptions(),
        target="current_filtered_view",
        filtered_columns=["designator", "comment"],
    )

    assert result.rows_exported == 1
    assert exporter.called["method"] == "filtered_view"
    assert exporter.called["columns"] == ["designator", "comment"]


@pytest.mark.anyio
async def test_export_use_case_requires_columns_for_filtered_view(tmp_path: Path) -> None:
    rows = [BomRow(project_id=1, designator="R1")]
    use_case = ExportBomUseCase(_FakeExporter())

    with pytest.raises(ValueError):
        await use_case.export(
            rows,
            tmp_path / "filtered.xlsx",
            ExportOptions(),
            target="filtered_view",
            filtered_columns=[],
        )


@pytest.mark.anyio
async def test_export_use_case_rejects_unknown_target(tmp_path: Path) -> None:
    rows = [BomRow(project_id=1, designator="R1")]
    use_case = ExportBomUseCase(_FakeExporter())

    with pytest.raises(ValueError):
        await use_case.export(
            rows,
            tmp_path / "unknown.xlsx",
            ExportOptions(),
            target="unknown_target",
        )
