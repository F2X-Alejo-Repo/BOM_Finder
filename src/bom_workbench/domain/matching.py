"""Deterministic replacement matching with transparent scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .entities import BomRow
from .normalization import NormalizationService
from .value_objects import ReplacementCandidate

__all__ = ["MatchScore", "MatchingEngine"]


@dataclass(slots=True, frozen=True)
class MatchScore:
    """Transparent match result for a candidate replacement."""

    total: float
    breakdown: dict[str, float]
    explanation: str
    tier: str = "heuristic"


class MatchingEngine:
    """Tiered replacement matcher with deterministic explanations."""

    TIERS: tuple[tuple[str, float], ...] = (
        ("exact_lcsc", 1.0),
        ("exact_mpn", 0.95),
        ("url_resolved", 0.9),
        ("strong_parametric", 0.8),
        ("heuristic", 0.6),
        ("llm_ranked", 0.4),
    )

    WEIGHTS: dict[str, float] = {
        "value_match": 0.30,
        "footprint_match": 0.25,
        "voltage_compat": 0.12,
        "tolerance_compat": 0.08,
        "temp_compat": 0.05,
        "dielectric_match": 0.05,
        "lifecycle_safety": 0.07,
        "stock_health": 0.05,
        "evidence_confidence": 0.03,
    }

    _VOLTAGE_PATTERN = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(mv|v|kv)\b", re.IGNORECASE)
    _TOLERANCE_PATTERN = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
    _TEMP_RANGE_PATTERN = re.compile(
        r"(-?\d+(?:\.\d+)?)\s*(?:c|deg\s*c)?\s*(?:to|-|~|through)\s*(-?\d+(?:\.\d+)?)\s*(?:c|deg\s*c)?",
        re.IGNORECASE,
    )
    _TEMP_SINGLE_PATTERN = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:c|deg\s*c)\b", re.IGNORECASE)
    _TECH_PATTERNS = (
        "x7r",
        "x5r",
        "c0g",
        "np0",
        "y5v",
        "ceramic",
        "electrolytic",
        "tantalum",
        "film",
        "resistor",
        "inductor",
        "ferrite",
    )

    def __init__(self, normalizer: NormalizationService | None = None) -> None:
        self._normalizer = normalizer or NormalizationService()

    def compute_match_score(
        self,
        original: BomRow,
        candidate: ReplacementCandidate,
    ) -> MatchScore:
        """Compute a transparent weighted score for a candidate."""

        tier = self._resolve_tier(original, candidate)
        if tier is not None:
            total, explanation = self._tier_match_details(tier, original, candidate)
            return MatchScore(
                total=total,
                breakdown={"identifier_match": total},
                explanation=explanation,
                tier=tier,
            )

        factor_scores = {
            "value_match": self._score_value_match(original, candidate),
            "footprint_match": self._score_footprint_match(original, candidate),
            "voltage_compat": self._score_voltage_compat(original, candidate),
            "tolerance_compat": self._score_tolerance_compat(original, candidate),
            "temp_compat": self._score_temp_compat(original, candidate),
            "dielectric_match": self._score_dielectric_match(original, candidate),
            "lifecycle_safety": self._score_lifecycle(candidate),
            "stock_health": self._score_stock(candidate),
            "evidence_confidence": self._score_confidence(candidate),
        }

        breakdown = {
            name: round(score * self.WEIGHTS[name], 6)
            for name, score in factor_scores.items()
        }
        total = round(sum(breakdown.values()), 6)
        explanation = self._build_explanation(original, candidate, factor_scores, breakdown, total)
        return MatchScore(total=total, breakdown=breakdown, explanation=explanation)

    def rank_candidates(
        self,
        original: BomRow,
        candidates: list[ReplacementCandidate] | tuple[ReplacementCandidate, ...] | Any,
    ) -> list[tuple[ReplacementCandidate, MatchScore]]:
        """Score and sort candidates from best to worst."""

        scored = [(candidate, self.compute_match_score(original, candidate)) for candidate in candidates]
        return sorted(
            scored,
            key=lambda item: (-item[1].total, self._candidate_sort_key(item[0])),
        )

    def _resolve_tier(self, original: BomRow, candidate: ReplacementCandidate) -> str | None:
        original_lcsc = self._normalized_identifier(self._get_text(original, "lcsc_part_number"))
        candidate_lcsc = self._normalized_identifier(
            self._get_text(candidate, "lcsc_part_number", "part_number")
        )
        if original_lcsc and candidate_lcsc and original_lcsc == candidate_lcsc:
            return "exact_lcsc"

        original_mpn = self._normalized_identifier(self._get_text(original, "mpn"))
        candidate_mpn = self._normalized_identifier(self._get_text(candidate, "mpn"))
        if original_mpn and candidate_mpn and original_mpn == candidate_mpn:
            return "exact_mpn"

        original_url = self._normalized_url(self._get_text(original, "lcsc_link", "source_url"))
        candidate_url = self._normalized_url(self._get_text(candidate, "lcsc_link", "source_url"))
        if original_url and candidate_url and original_url == candidate_url:
            return "url_resolved"

        return None

    def _tier_match_details(
        self,
        tier: str,
        original: BomRow,
        candidate: ReplacementCandidate,
    ) -> tuple[float, str]:
        _, score = next((name, value) for name, value in self.TIERS if name == tier)
        explanation = (
            f"{tier.replace('_', ' ')} match between "
            f"{self._best_label(original)} and {self._best_label(candidate)}."
        )
        return score, explanation

    def _score_value_match(self, original: BomRow, candidate: ReplacementCandidate) -> float:
        original_values = self._interesting_texts(
            original,
            "comment",
            "value_raw",
            "param_summary",
            "mpn",
        )
        candidate_values = self._interesting_texts(
            candidate,
            "value_summary",
            "description",
            "part_number",
            "mpn",
        )
        return self._best_text_score(original_values, candidate_values)

    def _score_footprint_match(self, original: BomRow, candidate: ReplacementCandidate) -> float:
        original_values = self._interesting_texts(original, "footprint", "package", "category")
        candidate_values = self._interesting_texts(candidate, "footprint", "package", "description")

        exact = self._best_text_score(original_values, candidate_values)
        if exact >= 1.0:
            return 1.0

        original_family = self._footprint_family(original_values)
        candidate_family = self._footprint_family(candidate_values)
        if original_family and candidate_family and original_family == candidate_family:
            return 0.8

        ratio = self._best_similarity(original_values, candidate_values)
        if ratio >= 0.85:
            return 0.5

        return 0.0

    def _score_voltage_compat(self, original: BomRow, candidate: ReplacementCandidate) -> float:
        original_voltage = self._extract_voltage(
            self._interesting_texts(original, "comment", "value_raw", "param_summary")
        )
        candidate_voltage = self._extract_voltage(
            self._interesting_texts(candidate, "value_summary", "description", "part_number")
        )
        if original_voltage is None or candidate_voltage is None:
            return 0.3
        return 1.0 if candidate_voltage >= original_voltage else 0.0

    def _score_tolerance_compat(self, original: BomRow, candidate: ReplacementCandidate) -> float:
        original_tolerance = self._extract_tolerance(
            self._interesting_texts(original, "comment", "value_raw", "param_summary")
        )
        candidate_tolerance = self._extract_tolerance(
            self._interesting_texts(candidate, "value_summary", "description", "part_number")
        )
        if original_tolerance is None or candidate_tolerance is None:
            return 0.3
        return 1.0 if candidate_tolerance <= original_tolerance else 0.5

    def _score_temp_compat(self, original: BomRow, candidate: ReplacementCandidate) -> float:
        original_range = self._extract_temperature_range(
            self._interesting_texts(original, "comment", "value_raw", "param_summary")
        )
        candidate_range = self._extract_temperature_range(
            self._interesting_texts(candidate, "value_summary", "description", "part_number")
        )
        if original_range is None or candidate_range is None:
            return 0.3

        original_min, original_max = original_range
        candidate_min, candidate_max = candidate_range
        if candidate_min <= original_min and candidate_max >= original_max:
            return 1.0
        if candidate_max >= original_min and candidate_min <= original_max:
            return 0.5
        return 0.0

    def _score_dielectric_match(self, original: BomRow, candidate: ReplacementCandidate) -> float:
        original_tokens = self._technology_tokens(
            self._interesting_texts(original, "comment", "value_raw", "param_summary")
        )
        candidate_tokens = self._technology_tokens(
            self._interesting_texts(candidate, "value_summary", "description", "part_number")
        )
        if not original_tokens or not candidate_tokens:
            return 0.3
        if original_tokens.intersection(candidate_tokens):
            return 1.0
        if any(
            self._token_family(token) in {self._token_family(item) for item in candidate_tokens}
            for token in original_tokens
        ):
            return 0.8
        return 0.0

    def _score_lifecycle(self, candidate: ReplacementCandidate) -> float:
        lifecycle = self._normalized_status(
            self._get_text(candidate, "lifecycle_status", "lifecycle", "status")
        )
        mapping = {
            "active": 1.0,
            "nrnd": 0.4,
            "last_time_buy": 0.2,
            "ltb": 0.2,
            "eol": 0.0,
            "obsolete": 0.0,
            "unknown": 0.3,
            "": 0.3,
        }
        return mapping.get(lifecycle, 0.3)

    def _score_stock(self, candidate: ReplacementCandidate) -> float:
        stock_qty = self._get_int(candidate, "stock_qty")
        if stock_qty is not None:
            if stock_qty <= 0:
                return 0.0
            if stock_qty <= 10:
                return 0.4
            if stock_qty <= 100:
                return 0.8
            return 1.0

        stock_status = self._normalized_status(self._get_text(candidate, "stock_status", "stock_bucket"))
        mapping = {
            "high": 1.0,
            "in_stock": 1.0,
            "available": 1.0,
            "medium": 0.8,
            "limited": 0.8,
            "low": 0.4,
            "out": 0.0,
            "out_of_stock": 0.0,
            "unavailable": 0.0,
            "unknown": 0.2,
            "": 0.2,
        }
        return mapping.get(stock_status, 0.2)

    def _score_confidence(self, candidate: ReplacementCandidate) -> float:
        confidence = self._normalized_status(self._get_text(candidate, "confidence", "source_confidence"))
        mapping = {
            "very_high": 1.0,
            "high": 1.0,
            "medium": 0.6,
            "low": 0.3,
            "very_low": 0.2,
            "none": 0.2,
            "unknown": 0.2,
            "": 0.2,
        }
        return mapping.get(confidence, 0.2)

    def _build_explanation(
        self,
        original: BomRow,
        candidate: ReplacementCandidate,
        factor_scores: dict[str, float],
        breakdown: dict[str, float],
        total: float,
    ) -> str:
        parts = [
            f"Compared {self._best_label(original)} against {self._best_label(candidate)}.",
        ]

        positive: list[str] = []
        caution: list[str] = []
        for name, raw_score in factor_scores.items():
            contribution = breakdown[name]
            label = name.replace("_", " ")
            if raw_score >= 0.9:
                positive.append(f"{label} +{contribution:.2f}")
            elif raw_score <= 0.3:
                caution.append(f"{label} {contribution:.2f}")

        if positive:
            parts.append("Strengths: " + ", ".join(positive) + ".")
        if caution:
            parts.append("Conservative factors: " + ", ".join(caution) + ".")
        parts.append(f"Total score {total:.3f}.")
        return " ".join(parts)

    def _best_text_score(self, left_values: list[str], right_values: list[str]) -> float:
        best = 0.0
        for left in left_values:
            for right in right_values:
                best = max(best, self._text_score(left, right))
                if best >= 1.0:
                    return 1.0
        return best

    def _best_similarity(self, left_values: list[str], right_values: list[str]) -> float:
        best = 0.0
        for left in left_values:
            for right in right_values:
                best = max(best, SequenceMatcher(None, left, right).ratio())
        return best

    def _text_score(self, left: str, right: str) -> float:
        left_norm = self._normalized_text(left)
        right_norm = self._normalized_text(right)
        if not left_norm or not right_norm:
            return 0.0
        if left_norm == right_norm:
            return 1.0

        left_numeric = self._normalized_numeric_signature(left_norm)
        right_numeric = self._normalized_numeric_signature(right_norm)
        if left_numeric and left_numeric == right_numeric:
            return 0.9

        ratio = SequenceMatcher(None, left_norm, right_norm).ratio()
        if ratio >= 0.85:
            return 0.5
        return 0.0

    def _normalized_text(self, text: object | None) -> str:
        return self._normalizer.normalize_value(self._coerce_scalar(text)).casefold()

    def _normalized_identifier(self, text: object | None) -> str:
        return self._normalized_text(text).replace(" ", "")

    def _normalized_url(self, text: object | None) -> str:
        normalized = self._normalizer.normalize_value(self._coerce_scalar(text))
        if not normalized:
            return ""

        parsed = urlsplit(normalized)
        if not parsed.scheme or not parsed.netloc:
            return ""
        path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))

    def _normalized_numeric_signature(self, text: str) -> str:
        signature = []
        for match in re.finditer(r"\d+(?:\.\d+)?\s*[a-z%]+|\d+(?:\.\d+)?", text):
            signature.append(match.group(0).replace(" ", ""))
        return "|".join(signature)

    def _extract_voltage(self, values: list[str]) -> float | None:
        for value in values:
            match = self._VOLTAGE_PATTERN.search(value)
            if match:
                amount = float(match.group(1))
                unit = match.group(2).lower()
                multiplier = {"mv": 0.001, "v": 1.0, "kv": 1000.0}[unit]
                return amount * multiplier
        return None

    def _extract_tolerance(self, values: list[str]) -> float | None:
        for value in values:
            match = self._TOLERANCE_PATTERN.search(value)
            if match:
                return float(match.group(1))
        return None

    def _extract_temperature_range(self, values: list[str]) -> tuple[float, float] | None:
        for value in values:
            range_match = self._TEMP_RANGE_PATTERN.search(value)
            if range_match:
                low = float(range_match.group(1))
                high = float(range_match.group(2))
                return (min(low, high), max(low, high))

            single_match = self._TEMP_SINGLE_PATTERN.search(value)
            if single_match:
                point = float(single_match.group(1))
                return (point, point)
        return None

    def _technology_tokens(self, values: list[str]) -> set[str]:
        tokens: set[str] = set()
        for value in values:
            normalized = self._normalized_text(value)
            for token in self._TECH_PATTERNS:
                if token in normalized:
                    tokens.add(token)
        return tokens

    def _footprint_family(self, values: list[str]) -> str:
        for value in values:
            normalized = self._normalized_text(value)
            if not normalized:
                continue
            match = re.search(r"\b(\d{4})\b", normalized)
            if match:
                return match.group(1)
            compact = re.sub(r"[^a-z0-9]+", "", normalized)
            if compact:
                return compact
        return ""

    def _token_family(self, token: str) -> str:
        compact = re.sub(r"[^a-z0-9]+", "", token.casefold())
        match = re.search(r"\d{4}", compact)
        if match:
            return match.group(0)
        return compact

    def _interesting_texts(self, obj: Any, *names: str) -> list[str]:
        values: list[str] = []
        for name in names:
            value = getattr(obj, name, None)
            if value is None:
                continue
            normalized = self._normalizer.normalize_value(self._coerce_scalar(value))
            if normalized:
                values.append(normalized)
        return values

    def _best_label(self, obj: Any) -> str:
        for name in ("lcsc_part_number", "part_number", "mpn", "designator", "description", "comment"):
            value = getattr(obj, name, None)
            if value is not None:
                text = self._normalizer.normalize_value(self._coerce_scalar(value))
                if text:
                    return text
        return obj.__class__.__name__

    def _get_text(self, obj: Any, *names: str) -> str:
        for name in names:
            value = getattr(obj, name, None)
            if value is None:
                continue
            text = self._normalizer.normalize_value(self._coerce_scalar(value))
            if text:
                return text
        return ""

    def _get_int(self, obj: Any, *names: str) -> int | None:
        for name in names:
            value = getattr(obj, name, None)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                text = self._normalizer.normalize_value(value)
                if text.isdigit():
                    return int(text)
        return None

    def _normalized_status(self, text: str) -> str:
        normalized = self._normalizer.normalize_value(text).casefold()
        normalized = normalized.replace(" ", "_").replace("-", "_")
        normalized = re.sub(r"[^a-z0-9_]+", "", normalized)
        replacements = {
            "inproduction": "active",
            "production": "active",
            "available": "high",
            "instock": "high",
            "in_stock": "high",
            "outofstock": "out",
            "out_of_stock": "out",
            "notrecommendedfornewdesigns": "nrnd",
            "not_recommended_for_new_designs": "nrnd",
            "lasttimebuy": "last_time_buy",
            "endoflife": "eol",
        }
        return replacements.get(normalized, normalized)

    def _candidate_sort_key(self, candidate: ReplacementCandidate) -> str:
        return self._best_label(candidate).casefold()

    def _coerce_scalar(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return getattr(value, "value")
        return value
