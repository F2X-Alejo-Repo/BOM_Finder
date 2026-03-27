"""Tests for column header matching and preprocessing."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from bom_workbench.domain.normalization import NormalizationService
from bom_workbench.domain.value_objects import ColumnMapping


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _read_headers(filename: str) -> list[str]:
    with (FIXTURES / filename).open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def _build_mappings(service: NormalizationService, headers: list[str]) -> list[ColumnMapping]:
    mappings: list[ColumnMapping] = []
    for header in headers:
        canonical = service.match_header(header)
        if canonical is not None:
            mappings.append(ColumnMapping(raw_column=header, canonical_field=canonical))
    return mappings


@pytest.fixture()
def service() -> NormalizationService:
    return NormalizationService()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Designator", "designator"),
        ("DESIGNATOR", "designator"),
        ("designators", "designator"),
        ("Reference", "designator"),
        ("  Reference  ", "designator"),
        ("Ref_Des", "designator"),
        ("ref-des", "designator"),
        ("Value", "comment"),
        ("COMMENT", "comment"),
        ("Footprint", "footprint"),
        ("PCB Footprint", "footprint"),
        ("pcb_footprint", "footprint"),
        ("Package", "footprint"),
        ("LCSC Part #", "lcsc_part_number"),
        ("LCSC Part Number", "lcsc_part_number"),
        ("lcsc pn", "lcsc_part_number"),
        ("LCSC_PN", "lcsc_part_number"),
        ("LCSC Link", "lcsc_link"),
        ("Supplier URL", "lcsc_link"),
        ("Part Link", "lcsc_link"),
        ("Qty", "quantity"),
        ("Manufacturer", "manufacturer"),
        ("MPN", "mpn"),
    ],
)
def test_match_header_aliases_and_preprocessing(service: NormalizationService, raw: str, expected: str) -> None:
    assert service.match_header(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["Random Column", "", "   ", "Revision", "Sheet", "Assembly Notes"],
)
def test_match_header_unmapped(service: NormalizationService, raw: str) -> None:
    assert service.match_header(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  LCSC-Part.Number  ", "lcsc part number"),
        ("Ref_Des", "ref des"),
        ("Part/Link", "part link"),
        ("PCB.Footprint", "pcb footprint"),
        ("  Multiple   Spaces ", "multiple spaces"),
        ("Val-ue", "val ue"),
    ],
)
def test_normalize_header_preprocessing(service: NormalizationService, raw: str, expected: str) -> None:
    assert service.normalize_header(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" R1 , R2;R3 | R4\nR5 ", ["R1", "R2", "R3", "R4", "R5"]),
        (["R1", "R2, R3", "R4"], ["R1", "R2", "R3", "R4"]),
        ("R1, R2, R1", ["R1", "R2"]),
        ("A1-A3", ["A1", "A2", "A3"]),
        ("R1-R3", ["R1", "R2", "R3"]),
    ],
)
def test_parse_designators(service: NormalizationService, raw: object, expected: list[str]) -> None:
    assert service.parse_designators(raw) == expected


def test_build_mappings_from_standard_fixture(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_standard.csv")
    mappings = _build_mappings(service, headers)
    assert [mapping.canonical_field for mapping in mappings] == [
        "designator",
        "comment",
        "footprint",
        "lcsc_part_number",
        "lcsc_link",
    ]


def test_weird_headers_fixture_maps_through_preprocessing(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_weird_headers.csv")
    mappings = _build_mappings(service, headers)
    assert {mapping.canonical_field for mapping in mappings} == {
        "designator",
        "comment",
        "footprint",
        "lcsc_part_number",
        "lcsc_link",
        "quantity",
        "manufacturer",
    }
    assert service.normalize_header(headers[0]) == "reference"
    assert service.normalize_header(headers[2]) == "pcb footprint"


def test_missing_cols_fixture_leaves_expected_columns_unmapped(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_missing_cols.csv")
    mappings = _build_mappings(service, headers)
    canonical_fields = {mapping.canonical_field for mapping in mappings}
    assert canonical_fields == {"designator", "comment", "footprint"}
    assert service.match_header("LCSC Part #") == "lcsc_part_number"


def test_extra_cols_fixture_preserves_unmapped_columns(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_extra_cols.csv")
    mappings = _build_mappings(service, headers)
    assert "comment" in {mapping.canonical_field for mapping in mappings}
    assert service.match_header("Supplier") is None
    assert service.match_header("Internal Status") is None
    assert service.match_header("Notes") is None


def test_quoted_fixture_headers_still_match(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_quoted.csv")
    mappings = _build_mappings(service, headers)
    assert [mapping.canonical_field for mapping in mappings] == [
        "designator",
        "comment",
        "footprint",
        "lcsc_part_number",
        "lcsc_link",
    ]


def test_malformed_fixture_headers_are_still_readable(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_malformed.csv")
    mappings = _build_mappings(service, headers)
    assert mappings[0].canonical_field == "designator"
    assert "comment" in {mapping.canonical_field for mapping in mappings}


def test_utf8_bom_fixture_reads_via_sig_encoding(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_utf8_bom.csv")
    assert headers[0] == "Designator"
    assert service.match_header(headers[4]) == "lcsc_link"


def test_large_fixture_has_stable_header_mapping(service: NormalizationService) -> None:
    headers = _read_headers("sample_bom_large.csv")
    mappings = _build_mappings(service, headers)
    assert [mapping.canonical_field for mapping in mappings[:5]] == [
        "designator",
        "comment",
        "footprint",
        "lcsc_part_number",
        "lcsc_link",
    ]


def test_duplicate_aliases_flag_ambiguity_within_same_canonical_group(service: NormalizationService) -> None:
    headers = ["Reference", "REFS", "Designator", "Random"]
    mappings = _build_mappings(service, headers)
    counts = Counter(mapping.canonical_field for mapping in mappings)
    assert counts["designator"] == 3
    assert counts["comment"] == 0
    assert sum(1 for header in headers if service.match_header(header) is None) == 1


def test_unknown_fields_remain_unmapped_in_mixed_header_set(service: NormalizationService) -> None:
    headers = ["Designator", "Mystery Field", "Footprint", "Another Unknown"]
    mappings = _build_mappings(service, headers)
    assert [mapping.canonical_field for mapping in mappings] == ["designator", "footprint"]
    assert service.match_header("Mystery Field") is None
    assert service.match_header("Another Unknown") is None
