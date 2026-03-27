"""Unit tests for CSV parsing behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

csv_parser_module = pytest.importorskip("bom_workbench.infrastructure.csv.parser")


CsvParser = csv_parser_module.CsvParser


def write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path


def write_bytes(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_detect_encoding_handles_utf8_bom(tmp_path: Path) -> None:
    parser = CsvParser()
    path = write_bytes(
        tmp_path / "utf8_bom.csv",
        b"\xef\xbb\xbfDesignator,Comment\nR1,100K\n",
    )

    encoding = parser.detect_encoding(path)

    assert encoding.replace("_", "-").lower() in {"utf-8-sig", "utf-8"}


def test_detect_encoding_handles_latin1(tmp_path: Path) -> None:
    parser = CsvParser()
    path = write_text(tmp_path / "latin1.csv", "Designator,Comment\nR1,Resistor caf\xe9\n", "latin-1")

    assert parser.detect_encoding(path).lower() in {
        "iso-8859-1",
        "latin-1",
        "cp1252",
        "windows-1252",
        "cp1250",
    }


@pytest.mark.parametrize(
    ("delimiter", "content"),
    [
        (",", "Designator,Comment\nR1,100K\n"),
        (";", "Designator;Comment\nR1;100K\n"),
        ("\t", "Designator\tComment\nR1\t100K\n"),
        ("|", "Designator|Comment\nR1|100K\n"),
    ],
)
def test_detect_delimiter_handles_common_separators(tmp_path: Path, delimiter: str, content: str) -> None:
    parser = CsvParser()
    path = write_text(tmp_path / "delimited.csv", content)

    assert parser.detect_delimiter(path, "utf-8") == delimiter


def test_parse_preserves_quoted_fields(tmp_path: Path) -> None:
    parser = CsvParser()
    path = write_text(
        tmp_path / "quoted.csv",
        'Designator,Comment,Footprint\n"R1, R2","100K, 1%","R_0402_1005Metric"\n',
    )

    result = parser.parse(path)

    assert result.row_count == 1
    assert result.headers == ["Designator", "Comment", "Footprint"]
    assert result.rows[0]["Designator"] == "R1, R2"
    assert result.rows[0]["Comment"] == "100K, 1%"
    assert result.rows[0]["Footprint"] == "R_0402_1005Metric"


def test_parse_preserves_multiline_quoted_fields(tmp_path: Path) -> None:
    parser = CsvParser()
    path = write_text(
        tmp_path / "multiline.csv",
        'Designator,Comment\nR1,"Line 1\nLine 2"\n',
    )

    result = parser.parse(path)

    assert result.row_count == 1
    assert result.rows[0]["Comment"] == "Line 1\nLine 2"


def test_parse_empty_file_returns_empty_result(tmp_path: Path) -> None:
    parser = CsvParser()
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    result = parser.parse(path)

    assert result.file_path == str(path)
    assert result.row_count == 0
    assert result.headers == []
    assert result.rows == []
    assert result.parse_warnings == []


def test_parse_headers_only_file(tmp_path: Path) -> None:
    parser = CsvParser()
    path = write_text(tmp_path / "headers_only.csv", "Designator,Comment,Footprint\n")

    result = parser.parse(path)

    assert result.row_count == 0
    assert result.headers == ["Designator", "Comment", "Footprint"]
    assert result.rows == []


def test_parse_malformed_rows_preserves_data_and_warns(tmp_path: Path) -> None:
    parser = CsvParser()
    path = write_text(
        tmp_path / "malformed.csv",
        "Designator,Comment,Footprint\nR1,100K,R_0402\nR2,1K\nR3,10K,R_0603,EXTRA\n",
    )

    result = parser.parse(path)

    assert result.row_count == 3
    assert len(result.rows) == 3
    assert result.rows[0]["Comment"] == "100K"
    assert result.parse_warnings


def test_parse_fixture_sample_standard_csv(tmp_path: Path) -> None:
    parser = CsvParser()
    fixture = tmp_path / "sample_bom_standard.csv"
    write_text(
        fixture,
        "Designator,Comment,Footprint,LCSC Part #,LCSC Link\n"
        '"R1, R2, R3, R4",100K,R_0402_1005Metric,C25744,https://jlcpcb.com/parts/C25744\n'
        '"C1, C2",100nF,C_0402_1005Metric,C1525,https://jlcpcb.com/parts/C1525\n'
        "U1,STM32F405RGT6,LQFP-64_10x10mm_P0.5mm,C15742,https://jlcpcb.com/parts/C15742\n",
    )

    result = parser.parse(fixture)

    assert result.row_count == 3
    assert result.rows[0]["Designator"] == "R1, R2, R3, R4"
    assert result.rows[2]["LCSC Part #"] == "C15742"
