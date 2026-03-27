"""Deterministic CSV header matching for BOM imports."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from ...domain import ColumnMapping
from ...domain.normalization import NormalizationService

__all__ = ["ColumnMatcher"]


class ColumnMatcher:
    """Match raw CSV headers to canonical BOM fields."""

    COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
        "designator": (
            r"^designators?$",
            r"^references?$",
            r"^refs?$",
            r"^ref\s*des(ignators?)?$",
        ),
        "comment": (
            r"^comments?$",
            r"^values?$",
            r"^vals?$",
            r"^description$",
            r"^part\s*description$",
        ),
        "footprint": (
            r"^footprints?$",
            r"^packages?$",
            r"^pcb\s*footprints?$",
            r"^land\s*patterns?$",
        ),
        "lcsc_link": (
            r"^lcsc\s*links?$",
            r"^lcsc\s*urls?$",
            r"^supplier\s*links?$",
            r"^part\s*links?$",
            r"^supplier\s*urls?$",
        ),
        "lcsc_part_number": (
            r"^lcsc\s*part\s*(?:numbers?|#|no)$",
            r"^lcsc\s*(?:pn|no|#)$",
            r"^part\s*(?:numbers?|#)$",
            r"^supplier\s*part\s*(?:numbers?|#)$",
        ),
        "manufacturer": (
            r"^manufacturers?$",
            r"^mfg$",
            r"^mfr$",
        ),
        "mpn": (
            r"^mpn$",
            r"^mfg\s*part\s*(?:numbers?|#)$",
            r"^manufacturer\s*part\s*(?:numbers?|#)$",
        ),
        "quantity": (
            r"^qty$",
            r"^quantity$",
            r"^count$",
        ),
    }

    def __init__(self, normalizer: NormalizationService | None = None) -> None:
        self._normalizer = normalizer or NormalizationService()

    def match_header(self, raw_header: object | None) -> ColumnMapping | None:
        """Match one raw header to a canonical field."""

        normalized = self._preprocess(raw_header)
        if not normalized:
            return None

        canonical = self._match_normalized(normalized)
        if canonical is None:
            return None

        return ColumnMapping(raw_column=self._coerce_raw_header(raw_header), canonical_field=canonical)

    def match_headers(
        self,
        raw_headers: Sequence[object | None] | Iterable[object | None],
    ) -> tuple[list[ColumnMapping], list[str], list[str]]:
        """Match all headers and return mappings, unmapped columns, and warnings."""

        mappings: list[ColumnMapping] = []
        unmapped: list[str] = []
        warnings: list[str] = []
        seen_fields: dict[str, str] = {}

        for raw_header in raw_headers:
            raw_column = self._coerce_raw_header(raw_header)
            normalized = self._preprocess(raw_header)
            if not normalized:
                unmapped.append(raw_column)
                continue

            canonical = self._match_normalized(normalized)
            if canonical is None:
                unmapped.append(raw_column)
                continue

            if canonical in seen_fields:
                warnings.append(
                    f"Ambiguous column mapping for '{canonical}': "
                    f"kept '{seen_fields[canonical]}' and ignored '{raw_column}'."
                )
                continue

            seen_fields[canonical] = raw_column
            mappings.append(ColumnMapping(raw_column=raw_column, canonical_field=canonical))

        return mappings, unmapped, warnings

    def _match_normalized(self, normalized_header: str) -> str | None:
        for canonical_field, patterns in self.COLUMN_ALIASES.items():
            if normalized_header == canonical_field:
                return canonical_field
            for pattern in patterns:
                if re.fullmatch(pattern, normalized_header):
                    return canonical_field
        return None

    def _preprocess(self, raw_header: object | None) -> str:
        text = self._normalizer.normalize_value(raw_header, max_length=None)
        if not text:
            return ""

        text = text.strip().lower()
        text = text.replace("_", " ").replace("-", " ").replace(".", " ")
        text = re.sub(r"[^0-9a-z ]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _coerce_raw_header(self, raw_header: object | None) -> str:
        if raw_header is None:
            return ""
        return self._normalizer.normalize_value(raw_header, max_length=None)
