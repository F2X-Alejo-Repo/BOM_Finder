"""CSV parsing utilities for BOM imports."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TypeAlias

from charset_normalizer import from_path
from pydantic import Field

from ...domain.value_objects import DomainModel

CsvRow: TypeAlias = dict[str, str | list[str]]


class ParseResult(DomainModel):
    """Normalized result for a parsed CSV file."""

    file_path: str
    encoding: str
    delimiter: str
    headers: list[str] = Field(default_factory=list)
    rows: list[CsvRow] = Field(default_factory=list)
    row_count: int = 0
    parse_warnings: list[str] = Field(default_factory=list)


class CsvParser:
    """Parse CSV files using tolerant, production-safe defaults."""

    _SUPPORTED_DELIMITERS = [",", ";", "\t", "|"]
    _EXTRA_COLUMNS_KEY = "_extra_columns"
    _SAMPLE_SIZE = 8192
    _MISSING = object()

    def detect_encoding(self, path: Path) -> str:
        """Detect a file encoding with a safe utf-8 fallback."""

        try:
            result = from_path(path).best()
        except Exception:
            return "utf-8"

        if result is None or not result.encoding:
            return "utf-8"

        return result.encoding

    def detect_delimiter(self, path: Path, encoding: str) -> str:
        """Detect the most likely CSV delimiter."""

        sample = self._read_sample(path, encoding)
        if not sample:
            return ","

        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters=self._SUPPORTED_DELIMITERS,
            )
        except csv.Error:
            return self._fallback_delimiter(sample)

        if dialect.delimiter in self._SUPPORTED_DELIMITERS:
            return dialect.delimiter

        return self._fallback_delimiter(sample)

    def parse(self, path: Path) -> ParseResult:
        """Parse a CSV file and keep malformed rows visible through warnings."""

        encoding = self.detect_encoding(path)
        delimiter = self.detect_delimiter(path, encoding)
        headers: list[str] = []
        rows: list[CsvRow] = []
        warnings: list[str] = []

        with path.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline="",
        ) as handle:
            reader = csv.DictReader(
                handle,
                delimiter=delimiter,
                restkey=self._EXTRA_COLUMNS_KEY,
                restval=self._MISSING,
            )

            raw_headers = list(reader.fieldnames or [])
            headers = self._normalize_headers(raw_headers)
            if headers != raw_headers:
                reader.fieldnames = headers

            if not headers and path.stat().st_size > 0:
                warnings.append("CSV file does not contain headers.")

            duplicates = self._duplicate_headers(headers)
            if duplicates:
                warnings.append(
                    "Duplicate headers detected: " + ", ".join(duplicates),
                )

            for row_number, raw_row in enumerate(reader, start=2):
                normalized_row, row_warnings = self._normalize_row(
                    raw_row,
                    headers,
                    row_number,
                )
                rows.append(normalized_row)
                warnings.extend(row_warnings)

        return ParseResult(
            file_path=str(path),
            encoding=encoding,
            delimiter=delimiter,
            headers=headers,
            rows=rows,
            row_count=len(rows),
            parse_warnings=warnings,
        )

    def _read_sample(self, path: Path, encoding: str) -> str:
        try:
            with path.open(
                "r",
                encoding=encoding,
                errors="replace",
                newline="",
            ) as handle:
                return handle.read(self._SAMPLE_SIZE)
        except OSError:
            return ""

    def _fallback_delimiter(self, sample: str) -> str:
        counts = {
            delimiter: sample.count(delimiter)
            for delimiter in self._SUPPORTED_DELIMITERS
        }
        delimiter, count = max(counts.items(), key=lambda item: item[1])
        if count == 0:
            return ","
        return delimiter

    def _normalize_headers(self, headers: list[str]) -> list[str]:
        normalized = list(headers)
        if normalized:
            normalized[0] = normalized[0].lstrip("\ufeff")
        return normalized

    def _duplicate_headers(self, headers: list[str]) -> list[str]:
        seen: set[str] = set()
        duplicates: list[str] = []
        for header in headers:
            if header in seen and header not in duplicates:
                duplicates.append(header)
            seen.add(header)
        return duplicates

    def _normalize_row(
        self,
        raw_row: dict[str, str | list[str] | object],
        headers: list[str],
        row_number: int,
    ) -> tuple[CsvRow, list[str]]:
        normalized: CsvRow = {}
        warnings: list[str] = []

        for header in headers:
            value = raw_row.get(header, self._MISSING)
            if value is self._MISSING:
                normalized[header] = ""
                warnings.append(
                    f"Row {row_number}: missing value for column '{header}'.",
                )
                continue

            normalized[header] = self._coerce_cell(value)

        extras = raw_row.get(self._EXTRA_COLUMNS_KEY)
        if extras:
            extra_values = [self._coerce_cell(value) for value in extras]
            normalized[self._EXTRA_COLUMNS_KEY] = extra_values
            warnings.append(
                f"Row {row_number}: extra columns preserved in "
                f"'{self._EXTRA_COLUMNS_KEY}'.",
            )

        if not headers and not normalized:
            warnings.append(f"Row {row_number}: empty row encountered.")

        return normalized, warnings

    def _coerce_cell(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
