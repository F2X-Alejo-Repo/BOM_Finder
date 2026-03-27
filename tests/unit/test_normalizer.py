"""Unit tests for BOM row normalization behavior."""

from __future__ import annotations

import pytest

normalizer_module = pytest.importorskip("bom_workbench.infrastructure.csv.normalizer")


RowNormalizer = normalizer_module.RowNormalizer


def make_normalizer() -> RowNormalizer:
    return RowNormalizer()


def test_parse_designators_and_quantity_from_single_value() -> None:
    normalizer = make_normalizer()

    assert normalizer.parse_designators("R1") == ["R1"]
    assert normalizer.designator_quantity("R1") == 1


def test_parse_designators_expands_ranges_and_dedupes() -> None:
    normalizer = make_normalizer()

    assert normalizer.parse_designators("R1, R2, R3") == ["R1", "R2", "R3"]
    assert normalizer.parse_designators("R1 , R2 , R2") == ["R1", "R2"]
    assert normalizer.parse_designators("C1-C3") == ["C1", "C2", "C3"]


def test_value_maps_to_comment_and_value_raw() -> None:
    normalizer = make_normalizer()
    row = {"Designator": "R1", "Value": "100K"}

    result = normalizer.normalize([row], [], "demo.csv", 1)

    assert len(result.rows) == 1
    normalized = result.rows[0]
    assert normalized.comment == "100K"
    assert normalized.value_raw == "100K"


def test_multiple_urls_raise_warning_and_preserve_primary() -> None:
    normalizer = make_normalizer()
    row = {
        "Designator": "R1",
        "LCSC Link": "https://jlcpcb.com/parts/C25744;https://jlcpcb.com/parts/C99999",
    }

    result = normalizer.normalize([row], [], "demo.csv", 1)

    assert len(result.rows) == 1
    normalized = result.rows[0]
    assert normalized.lcsc_link == "https://jlcpcb.com/parts/C25744"
    assert normalized.validation_warnings
    assert "url" in normalized.validation_warnings.lower()


def test_multiple_part_numbers_raise_warning_and_preserve_primary() -> None:
    normalizer = make_normalizer()
    row = {
        "Designator": "R1",
        "LCSC Part #": "C25744, C99999",
    }

    result = normalizer.normalize([row], [], "demo.csv", 1)

    assert len(result.rows) == 1
    normalized = result.rows[0]
    assert normalized.lcsc_part_number == "C25744"
    assert normalized.validation_warnings
    assert "part" in normalized.validation_warnings.lower()


def test_empty_row_is_kept_with_warning() -> None:
    normalizer = make_normalizer()

    result = normalizer.normalize([{}], [], "demo.csv", 1)

    assert len(result.rows) == 1
    normalized = result.rows[0]
    assert normalized.row_state == "imported"
    assert normalized.validation_warnings


def test_whitespace_only_fields_are_cleaned() -> None:
    normalizer = make_normalizer()
    row = {"Designator": "  ", "Comment": "\t", "Footprint": "  R_0402  "}

    result = normalizer.normalize([row], [], "demo.csv", 1)

    normalized = result.rows[0]
    assert normalized.designator == ""
    assert normalized.comment == ""
    assert normalized.footprint == "R_0402"


def test_long_values_are_truncated_by_service() -> None:
    normalizer = make_normalizer()
    long_value = "A" * 600

    assert normalizer.normalize_value(long_value) == "A" * 512

