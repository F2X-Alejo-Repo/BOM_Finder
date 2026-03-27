"""Normalization helpers for BOM import and matching."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

__all__ = ["NormalizationService"]


class NormalizationService:
    """Pure, deterministic text normalization utilities."""

    _MULTI_VALUE_SPLIT = re.compile(r"[,\n;|]+")
    _WHITESPACE = re.compile(r"\s+")
    _NON_ALNUM = re.compile(r"[^0-9a-z ]+")
    _URL_PATTERN = re.compile(r"https?://[^\s,;|]+", re.IGNORECASE)
    _DESIGNATOR_RANGE = re.compile(
        r"^([A-Za-z]+)(\d+)\s*-\s*([A-Za-z]+)?(\d+)$",
        re.IGNORECASE,
    )

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
            r"^lcsc\s*part(?:\s*number|\s*no|\s*#)?$",
            r"^lcsc\s*(?:pn|no|#)$",
            r"^part(?:\s*number|\s*#)?$",
            r"^supplier\s*part(?:\s*number|\s*#)?$",
        ),
        "manufacturer": (
            r"^manufacturers?$",
            r"^mfg$",
            r"^mfr$",
        ),
        "mpn": (
            r"^mpn$",
            r"^mfg\s*part(?:\s*number|\s*#)?$",
            r"^manufacturer\s*part(?:\s*number|\s*#)?$",
        ),
        "quantity": (
            r"^qty$",
            r"^quantity$",
            r"^count$",
        ),
    }

    def normalize_header(self, raw_header: object | None) -> str:
        """Normalize a CSV header for stable matching."""

        text = self.normalize_value(raw_header, max_length=None)
        text = text.lower()
        text = text.replace("_", " ").replace("-", " ").replace(".", " ")
        text = text.replace("/", " ")
        text = self._NON_ALNUM.sub(" ", text)
        return self._WHITESPACE.sub(" ", text).strip()

    def normalize_value(self, raw_value: object | None, *, max_length: int | None = 512) -> str:
        """Normalize arbitrary cell values without altering meaning."""

        text = self._coerce_text(raw_value)
        if not text:
            return ""

        text = self._WHITESPACE.sub(" ", text).strip()

        if max_length is not None and len(text) > max_length:
            text = text[:max_length].rstrip()

        return text

    def match_header(self, raw_header: object | None) -> str | None:
        """Return the canonical field for a raw header, if any."""

        normalized = self.normalize_header(raw_header)
        if not normalized:
            return None

        for canonical, patterns in self.COLUMN_ALIASES.items():
            if normalized == canonical:
                return canonical
            for pattern in patterns:
                if re.fullmatch(pattern, normalized):
                    return canonical
        return None

    def split_multi_value(self, raw_value: object | None) -> list[str]:
        """Split a multi-value cell into normalized tokens."""

        text = self._coerce_text(raw_value)
        if not text:
            return []

        tokens = [self.normalize_value(token) for token in self._MULTI_VALUE_SPLIT.split(text)]
        return [token for token in tokens if token]

    def extract_primary_url(self, raw_value: object | None) -> str:
        """Return the first URL found in a cell, if any."""

        text = self._coerce_text(raw_value)
        if not text:
            return ""

        match = self._URL_PATTERN.search(text)
        if match:
            return match.group(0).rstrip(").,;")

        for token in self.split_multi_value(text):
            if token.lower().startswith(("http://", "https://")):
                return token.rstrip(").,;")
        return ""

    def extract_primary_part_number(self, raw_value: object | None) -> str:
        """Return the first likely part number from a multi-value cell."""

        for token in self.split_multi_value(raw_value):
            if token:
                return token
        return self.normalize_value(raw_value)

    def parse_designators(self, raw_value: object | None) -> list[str]:
        """Parse and normalize designator cells into an ordered list."""

        if raw_value is None:
            return []

        if isinstance(raw_value, Iterable) and not isinstance(raw_value, (str, bytes)):
            tokens: list[str] = []
            for item in raw_value:
                tokens.extend(self.parse_designators(item))
            return self._dedupe(tokens)

        text = self._coerce_text(raw_value)
        if not text:
            return []

        tokens: list[str] = []
        for chunk in self._MULTI_VALUE_SPLIT.split(text):
            token = self.normalize_value(chunk)
            if not token:
                continue

            expanded = self._expand_designator_range(token)
            if expanded is None:
                tokens.append(token)
            else:
                tokens.extend(expanded)

        return self._dedupe(tokens)

    def designator_quantity(self, raw_value: object | None) -> int:
        """Count parsed designators."""

        return len(self.parse_designators(raw_value))

    def _expand_designator_range(self, token: str) -> list[str] | None:
        match = self._DESIGNATOR_RANGE.fullmatch(token)
        if match is None:
            return None

        prefix_a, start_text, prefix_b, end_text = match.groups()
        prefix_b = prefix_b or prefix_a
        if prefix_a.lower() != prefix_b.lower():
            return None

        start = int(start_text)
        end = int(end_text)
        if end < start or end - start > 1000:
            return None

        return [f"{prefix_a}{index}" for index in range(start, end + 1)]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    def _coerce_text(self, raw_value: object | None) -> str:
        if raw_value is None:
            return ""

        if isinstance(raw_value, bytes):
            text = raw_value.decode("utf-8", errors="replace")
        else:
            text = str(raw_value)

        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\ufeff", "").replace("\x00", "")
        return text.replace("\r\n", "\n").replace("\r", "\n")
