"""Unit tests for KiCad footprint normalization in RowNormalizer."""

from __future__ import annotations

import pytest

from bom_workbench.infrastructure.csv.normalizer import RowNormalizer


@pytest.fixture()
def normalizer() -> RowNormalizer:
    return RowNormalizer()


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Plain package codes pass through unchanged (uppercased).
        ("0603", "0603"),
        ("0402", "0402"),
        ("0201", "0201"),
        ("0805", "0805"),
        ("1206", "1206"),
        # KiCad passive SMD footprints.
        ("Capacitor_SMD:C_0603_1608Metric", "0603"),
        ("Resistor_SMD:R_0402_1005Metric", "0402"),
        ("Resistor_SMD:R_0201_0603Metric", "0201"),
        ("Capacitor_SMD:C_0805_2012Metric", "0805"),
        ("Resistor_SMD:R_1206_3216Metric", "1206"),
        ("Capacitor_SMD:C_1210_3225Metric", "1210"),
        # KiCad IC footprints — SOIC.
        ("Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "SOIC-8"),
        ("Package_SO:SOIC-16_3.9x9.9mm_P1.27mm", "SOIC-16"),
        # KiCad IC footprints — SOT.
        ("Package_TO_SOT_SMD:SOT-23", "SOT-23"),
        ("Package_TO_SOT_SMD:SOT-23-5", "SOT-23-5"),
        ("Package_TO_SOT_SMD:SOT-223-3_TabPin2", "SOT-223-3"),
        # KiCad IC footprints — TSSOP.
        ("Package_SO:TSSOP-16_4.4x5mm_P0.65mm", "TSSOP-16"),
        # KiCad IC footprints — QFN.
        ("Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm", "QFN-32"),
        # No library prefix — just a footprint name with package code.
        ("C_0402_1005Metric", "0402"),
        ("SOIC-8_3.9x4.9mm", "SOIC-8"),
        # Empty / whitespace.
        ("", ""),
        ("   ", ""),
        # Unknown footprint with library prefix — strips prefix, keeps name.
        ("Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "PinHeader_1x02_P2.54mm_Vertical"),
        # Already normalized (no library prefix, no metric suffix).
        ("SOT-23", "SOT-23"),
    ],
)
def test_normalize_footprint(normalizer: RowNormalizer, raw: str, expected: str) -> None:
    assert normalizer._normalize_footprint(raw) == expected


def test_normalize_footprint_applied_during_row_normalization(normalizer: RowNormalizer) -> None:
    """End-to-end: footprint field is normalized when processing a CSV row."""
    from bom_workbench.domain.value_objects import ColumnMapping

    raw_rows = [
        {
            "Reference": "C1",
            "Value": "100nF",
            "Footprint": "Capacitor_SMD:C_0603_1608Metric",
            "LCSC Part #": "C14663",
        }
    ]
    mappings = [
        ColumnMapping(raw_column="Reference", canonical_field="designator"),
        ColumnMapping(raw_column="Value", canonical_field="comment"),
        ColumnMapping(raw_column="Footprint", canonical_field="footprint"),
        ColumnMapping(raw_column="LCSC Part #", canonical_field="lcsc_part_number"),
    ]
    result = normalizer.normalize(raw_rows, mappings, source_file="test.csv", project_id=1)

    assert len(result.rows) == 1
    assert result.rows[0].footprint == "0603"
    assert result.rows[0].lcsc_part_number == "C14663"
