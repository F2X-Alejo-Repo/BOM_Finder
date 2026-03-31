"""Parser for KiCad pick-and-place / Component Placement List (CPL) CSV files."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...domain.entities import CplEntry

__all__ = ["CplParser", "CplParseResult"]

# ---------------------------------------------------------------------------
# Column alias mapping
# ---------------------------------------------------------------------------
# KiCad exports CPL files with varying column names across versions and plugins.
# Map all known variants to a canonical field name.

_COLUMN_ALIASES: dict[str, str] = {
    # Designator / reference
    "ref": "designator",
    "reference": "designator",
    "references": "designator",
    "designator": "designator",
    "refdes": "designator",
    "component": "designator",
    # X position
    "posx": "x_pos",
    "pos x": "x_pos",
    "mid x": "x_pos",
    "midx": "x_pos",
    "x": "x_pos",
    "center-x(mm)": "x_pos",
    "centerx(mm)": "x_pos",
    "posx(mm)": "x_pos",
    # Y position
    "posy": "y_pos",
    "pos y": "y_pos",
    "mid y": "y_pos",
    "midy": "y_pos",
    "y": "y_pos",
    "center-y(mm)": "y_pos",
    "centery(mm)": "y_pos",
    "posy(mm)": "y_pos",
    # Rotation
    "rot": "rotation",
    "rotation": "rotation",
    "rotate": "rotation",
    "angle": "rotation",
    # Layer / side
    "side": "layer",
    "layer": "layer",
    "tb": "layer",
    # Value (optional)
    "val": "value",
    "value": "value",
    # Footprint (optional)
    "footprint": "footprint",
    "package": "footprint",
}

_LAYER_ALIASES: dict[str, str] = {
    "top": "Top",
    "t": "Top",
    "f": "Top",
    "f.cu": "Top",
    "front": "Top",
    "bottom": "Bottom",
    "b": "Bottom",
    "b.cu": "Bottom",
    "back": "Bottom",
}


@dataclass
class CplParseResult:
    """Result of parsing one CPL file."""

    entries: list[CplEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_file: str = ""
    skipped_rows: int = 0


class CplParser:
    """Parse KiCad CPL/pick-and-place CSV files into CplEntry records."""

    # Rows that are clearly header or comment lines (KiCad sometimes repeats headers mid-file).
    _SKIP_PATTERN = re.compile(r"^\s*#", re.IGNORECASE)

    def parse_file(
        self,
        path: str | Path,
        *,
        project_id: int,
    ) -> CplParseResult:
        """Read and parse a CPL file from disk."""
        path = Path(path)
        try:
            text = self._read_text(path)
        except OSError as exc:
            result = CplParseResult(source_file=str(path))
            result.warnings.append(f"Could not read file '{path.name}': {exc}")
            return result
        return self.parse_text(text, source_file=str(path), project_id=project_id)

    def parse_text(
        self,
        text: str,
        *,
        source_file: str = "",
        project_id: int,
    ) -> CplParseResult:
        """Parse CPL CSV text into CplEntry records."""
        result = CplParseResult(source_file=source_file)

        # Strip BOM marker.
        text = text.lstrip("\ufeff")

        # Filter comment lines and detect delimiter.
        lines = [line for line in text.splitlines() if not self._SKIP_PATTERN.match(line)]
        if not lines:
            result.warnings.append("File appears empty or contains only comments.")
            return result

        delimiter = self._detect_delimiter("\n".join(lines[:5]))
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)

        if reader.fieldnames is None:
            result.warnings.append("Could not read CSV headers from file.")
            return result

        col_map = self._build_column_map(list(reader.fieldnames))
        if "designator" not in col_map:
            result.warnings.append(
                "No designator/reference column found. "
                f"Headers: {', '.join(str(h) for h in reader.fieldnames)}"
            )
            return result

        for row_index, raw_row in enumerate(reader, start=2):  # 1-based, header is row 1
            entry = self._parse_row(raw_row, col_map, project_id=project_id, source_file=source_file)
            if entry is None:
                result.skipped_rows += 1
                continue
            result.entries.append(entry)

        if not result.entries and not result.warnings:
            result.warnings.append("No placement entries found in file.")

        return result

    def validate_against_bom(
        self,
        cpl_entries: list[CplEntry],
        bom_designators: list[str],
    ) -> list[str]:
        """Cross-validate CPL entries against BOM designators.

        Returns a list of warning/error strings. Empty list means everything matches.
        """
        cpl_refs: set[str] = {e.designator.strip().upper() for e in cpl_entries}
        bom_refs: set[str] = {d.strip().upper() for d in bom_designators if d.strip()}

        warnings: list[str] = []

        in_bom_not_cpl = bom_refs - cpl_refs
        in_cpl_not_bom = cpl_refs - bom_refs

        if in_bom_not_cpl:
            sorted_missing = sorted(in_bom_not_cpl)
            warnings.append(
                f"{len(sorted_missing)} BOM designator(s) have no CPL placement entry "
                f"(JLCPCB upload will fail): "
                + ", ".join(sorted_missing[:15])
                + (" …" if len(sorted_missing) > 15 else "")
            )

        if in_cpl_not_bom:
            sorted_extra = sorted(in_cpl_not_bom)
            warnings.append(
                f"{len(sorted_extra)} CPL designator(s) have no matching BOM row: "
                + ", ".join(sorted_extra[:15])
                + (" …" if len(sorted_extra) > 15 else "")
            )

        return warnings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_text(self, path: Path) -> str:
        """Read file with encoding detection (UTF-8 first, then latin-1 fallback)."""
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return path.read_text(encoding="latin-1")

    def _detect_delimiter(self, sample: str) -> str:
        for delim in (",", "\t", ";", "|"):
            if delim in sample:
                return delim
        return ","

    def _build_column_map(self, fieldnames: list[str]) -> dict[str, str]:
        """Map raw CSV column names to canonical CPL field names."""
        col_map: dict[str, str] = {}
        for raw_col in fieldnames:
            if raw_col is None:
                continue
            normalized = raw_col.strip().lower().replace(" ", "")
            canonical = _COLUMN_ALIASES.get(normalized)
            if canonical and canonical not in col_map:
                col_map[canonical] = raw_col
        return col_map

    def _parse_row(
        self,
        raw_row: dict[str, Any],
        col_map: dict[str, str],
        *,
        project_id: int,
        source_file: str,
    ) -> CplEntry | None:
        designator = self._get(raw_row, col_map, "designator").strip()
        if not designator:
            return None

        x_pos = self._get_float(raw_row, col_map, "x_pos")
        y_pos = self._get_float(raw_row, col_map, "y_pos")
        rotation = self._get_float(raw_row, col_map, "rotation")
        layer_raw = self._get(raw_row, col_map, "layer")
        layer = _LAYER_ALIASES.get(layer_raw.strip().lower(), layer_raw.strip() or "Top")
        value = self._get(raw_row, col_map, "value")
        footprint = self._get(raw_row, col_map, "footprint")

        return CplEntry(
            project_id=project_id,
            source_file=source_file,
            designator=designator,
            x_pos=x_pos,
            y_pos=y_pos,
            rotation=rotation,
            layer=layer,
            value=value,
            footprint=footprint,
        )

    def _get(self, row: dict[str, Any], col_map: dict[str, str], field_name: str) -> str:
        raw_col = col_map.get(field_name)
        if not raw_col:
            return ""
        value = row.get(raw_col, "")
        return str(value).strip() if value is not None else ""

    def _get_float(self, row: dict[str, Any], col_map: dict[str, str], field_name: str) -> float:
        text = self._get(row, col_map, field_name)
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0
