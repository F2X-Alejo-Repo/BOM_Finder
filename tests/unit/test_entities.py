"""Baseline tests for domain entity defaults and validation-friendly behavior."""

from __future__ import annotations

from datetime import datetime

import pytest


entities = pytest.importorskip("bom_workbench.domain.entities")


def test_bom_project_defaults_are_lightweight() -> None:
    """BomProject should be constructible without DB access or extra fields."""
    project = entities.BomProject(name="Demo project")

    assert project.id is None
    assert project.name == "Demo project"
    assert project.description == ""
    assert project.source_files == ""
    assert isinstance(project.created_at, datetime)
    assert isinstance(project.updated_at, datetime)
    assert project.rows == []


def test_bom_row_defaults_support_incremental_population() -> None:
    """BomRow should allow partial data loading with safe defaults."""
    row = entities.BomRow(project_id=1)

    assert row.id is None
    assert row.project_id == 1
    assert row.source_file == ""
    assert row.original_row_index == 0
    assert row.designator == ""
    assert row.comment == ""
    assert row.value_raw == ""
    assert row.footprint == ""
    assert row.lcsc_link == ""
    assert row.lcsc_part_number == ""
    assert row.designator_list == ""
    assert row.quantity == 0
    assert row.manufacturer == ""
    assert row.mpn == ""
    assert row.package == ""
    assert row.category == ""
    assert row.param_summary == ""
    assert row.stock_qty is None
    assert row.stock_status == ""
    assert row.lifecycle_status == "unknown"
    assert row.eol_risk == "unknown"
    assert row.lead_time == ""
    assert row.moq is None
    assert row.last_checked_at is None
    assert row.source_url == ""
    assert row.source_name == ""
    assert row.source_confidence == "none"
    assert row.sourcing_notes == ""
    assert row.replacement_candidate_part_number == ""
    assert row.replacement_candidate_link == ""
    assert row.replacement_candidate_mpn == ""
    assert row.replacement_rationale == ""
    assert row.replacement_match_score is None
    assert row.replacement_status == "none"
    assert row.user_accepted_replacement is False
    assert row.enrichment_provider == ""
    assert row.enrichment_model == ""
    assert row.enrichment_job_id == ""
    assert row.enrichment_version == ""
    assert row.evidence_blob == ""
    assert row.raw_provider_response == ""
    assert row.row_state == "imported"
    assert row.validation_warnings == ""
    assert isinstance(row.created_at, datetime)
    assert isinstance(row.updated_at, datetime)
    assert row.project is None


def test_bom_row_accepts_validation_friendly_values() -> None:
    """Row fields should accept the documented string values without coercion."""
    row = entities.BomRow(
        project_id=1,
        lifecycle_status="nrnd",
        stock_status="high",
        eol_risk="medium",
        source_confidence="low",
        replacement_status="candidates_found",
        row_state="queued",
    )

    assert row.lifecycle_status == "nrnd"
    assert row.stock_status == "high"
    assert row.eol_risk == "medium"
    assert row.source_confidence == "low"
    assert row.replacement_status == "candidates_found"
    assert row.row_state == "queued"

