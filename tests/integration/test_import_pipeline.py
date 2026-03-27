"""Integration tests for the CSV import pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlmodel import select

from bom_workbench.domain.entities import BomProject, BomRow
from bom_workbench.domain.value_objects import ColumnMapping
from bom_workbench.infrastructure.csv.column_matcher import ColumnMatcher
from bom_workbench.infrastructure.csv.normalizer import RowNormalizer
from bom_workbench.infrastructure.csv.parser import CsvParser
from bom_workbench.infrastructure.persistence.database import (
    DatabaseSettings,
    create_db_and_tables,
    create_engine_from_settings,
    create_session,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


async def _run_sync(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def _build_mappings(headers: list[str], matcher: ColumnMatcher) -> list[ColumnMapping]:
    mappings, _unmapped, _warnings = matcher.match_headers(headers)
    return mappings


def _persist_roundtrip(
    db_path: Path,
    project_name: str,
    source_file: str,
    normalized_rows: list[BomRow],
) -> tuple[BomProject, list[BomRow]]:
    settings = DatabaseSettings(db_path=db_path)
    engine = create_engine_from_settings(settings)
    create_db_and_tables(engine)

    with create_session(engine) as session:
        project = BomProject(name=project_name, source_files=source_file)
        session.add(project)
        session.commit()
        session.refresh(project)

        for row in normalized_rows:
            row.project_id = project.id or 0
            session.add(row)
        session.commit()

        saved_project = session.get(BomProject, project.id)
        saved_rows = list(
            session.exec(
                select(BomRow).where(BomRow.project_id == (project.id or 0)).order_by(BomRow.id)
            )
        )

    return saved_project, saved_rows


def test_import_pipeline_roundtrip_persists_project_and_rows(tmp_path: Path) -> None:
    fixture_path = FIXTURES / "sample_bom_standard.csv"
    parser = CsvParser()
    matcher = ColumnMatcher()
    normalizer = RowNormalizer()

    parse_result = parser.parse(fixture_path)
    mappings = _build_mappings(parse_result.headers, matcher)
    normalized = normalizer.normalize(
        parse_result.rows,
        mappings,
        parse_result.file_path,
        project_id=1,
    )

    db_path = tmp_path / "import_pipeline.sqlite"
    saved_project, saved_rows = asyncio.run(_run_sync(
        _persist_roundtrip,
        db_path,
        "sample_bom_standard",
        parse_result.file_path,
        normalized.rows,
    ))

    assert saved_project is not None
    assert saved_project.name == "sample_bom_standard"
    assert saved_project.source_files == parse_result.file_path
    assert len(saved_rows) == parse_result.row_count
    assert [row.designator for row in saved_rows] == ["R1, R2, R3, R4", "C1, C2", "U1"]
    assert saved_rows[0].comment == "100K"
    assert saved_rows[0].project_id == saved_project.id
    assert saved_rows[0].row_state == "imported"
    assert saved_rows[0].designator_list == '["R1","R2","R3","R4"]'
