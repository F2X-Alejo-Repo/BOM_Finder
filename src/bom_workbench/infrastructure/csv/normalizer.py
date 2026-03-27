"""Row normalization utilities for BOM CSV imports."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ...domain.entities import BomRow
from ...domain.enums import Confidence
from ...domain.normalization import NormalizationService
from ...domain.value_objects import ColumnMapping, ValidationWarning

__all__ = ["NormalizationResult", "RowNormalizer"]


class NormalizationResult(BaseModel):
    """Result of normalizing one CSV payload into BomRow entities."""

    model_config = ConfigDict(extra="forbid")

    rows: list[BomRow] = Field(default_factory=list)
    warnings: list[ValidationWarning] = Field(default_factory=list)
    skipped_count: int = 0


class RowNormalizer(NormalizationService):
    """Transforms raw parsed rows into canonical BomRow entities."""

    _URL_PATTERN = re.compile(r"https?://[^\s,;|]+", re.IGNORECASE)
    _VALUE_ALIASES = {
        "value",
        "values",
        "val",
        "vals",
        "description",
        "part description",
    }

    def normalize(
        self,
        raw_rows: Sequence[Mapping[str, Any]],
        column_mappings: Sequence[ColumnMapping],
        source_file: str,
        project_id: int,
    ) -> NormalizationResult:
        """Normalize raw rows into BomRow records without skipping any input."""

        rows: list[BomRow] = []
        warnings: list[ValidationWarning] = []

        for row_index, raw_row in enumerate(raw_rows, start=1):
            row_warnings: list[ValidationWarning] = []
            canonical_mappings = self._canonical_mapping_index(raw_row, column_mappings)
            row_kwargs: dict[str, Any] = {
                "project_id": project_id,
                "source_file": source_file,
                "original_row_index": row_index,
                "row_state": "imported",
            }

            designator_text = self._mapped_value(
                raw_row,
                canonical_mappings,
                "designator",
            )
            designators = self.parse_designators(designator_text)
            row_kwargs["designator"] = self.normalize_value(
                designator_text,
                max_length=None,
            )
            row_kwargs["designator_list"] = json.dumps(
                designators,
                ensure_ascii=True,
                separators=(",", ":"),
            )
            row_kwargs["quantity"] = self._resolve_quantity(
                designator_text=designator_text,
                mapped_quantity=self._mapped_value(
                    raw_row,
                    canonical_mappings,
                    "quantity",
                ),
            )

            for canonical_field in (
                "comment",
                "footprint",
                "lcsc_link",
                "lcsc_part_number",
                "manufacturer",
                "mpn",
                "package",
                "category",
                "param_summary",
                "source_url",
                "source_name",
                "source_confidence",
                "sourcing_notes",
                "replacement_candidate_part_number",
                "replacement_candidate_link",
                "replacement_candidate_mpn",
                "replacement_rationale",
                "replacement_status",
                "enrichment_provider",
                "enrichment_model",
                "enrichment_job_id",
                "enrichment_version",
                "evidence_blob",
                "raw_provider_response",
            ):
                raw_value = self._mapped_value(
                    raw_row,
                    canonical_mappings,
                    canonical_field,
                )
                if raw_value == "":
                    continue

                normalized_value = self._normalize_canonical_field(
                    canonical_field=canonical_field,
                    raw_value=raw_value,
                    row_index=row_index,
                    row_warnings=row_warnings,
                )

                if canonical_field == "comment" and self._is_value_like_source(
                    canonical_mappings,
                    "comment",
                ):
                    row_kwargs["value_raw"] = normalized_value

                row_kwargs[canonical_field] = normalized_value

            if "value_raw" not in row_kwargs:
                comment_value = self.normalize_value(
                    self._mapped_value(
                        raw_row,
                        canonical_mappings,
                        "comment",
                    ),
                    max_length=None,
                )
                if comment_value and self._is_value_like_source(
                    canonical_mappings,
                    "comment",
                ):
                    row_kwargs["value_raw"] = comment_value

            if "value_raw" not in row_kwargs:
                row_kwargs["value_raw"] = ""

            if not self._row_has_meaningful_content(row_kwargs):
                row_warnings.append(
                    self._warning(
                        code="empty_row",
                        message="Row contains no normalized values but was preserved.",
                        row_index=row_index,
                        severity=Confidence.LOW,
                    )
                )

            if row_warnings:
                row_kwargs["validation_warnings"] = self._serialize_warnings(
                    row_warnings,
                )
                warnings.extend(row_warnings)
            else:
                row_kwargs["validation_warnings"] = ""

            rows.append(BomRow(**row_kwargs))

        return NormalizationResult(rows=rows, warnings=warnings, skipped_count=0)

    def _canonical_mapping_index(
        self,
        raw_row: Mapping[str, Any],
        column_mappings: Sequence[ColumnMapping],
    ) -> dict[str, str]:
        mapping_index: dict[str, str] = {}
        for mapping in column_mappings:
            canonical = mapping.canonical_field.strip()
            if canonical and canonical not in mapping_index:
                mapping_index[canonical] = mapping.raw_column

        for raw_column in raw_row.keys():
            canonical = self.match_header(raw_column)
            if canonical and canonical not in mapping_index:
                mapping_index[canonical] = raw_column

        return mapping_index

    def _mapped_value(
        self,
        raw_row: Mapping[str, Any],
        canonical_mappings: Mapping[str, str],
        canonical_field: str,
    ) -> str:
        raw_column = canonical_mappings.get(canonical_field, "")
        if not raw_column:
            return ""

        raw_value = raw_row.get(raw_column, "")
        return self._normalize_cell_text(raw_value)

    def _normalize_canonical_field(
        self,
        *,
        canonical_field: str,
        raw_value: str,
        row_index: int,
        row_warnings: list[ValidationWarning],
    ) -> str:
        if canonical_field == "lcsc_link":
            return self._normalize_url_cell(
                raw_value,
                row_index=row_index,
                row_warnings=row_warnings,
            )

        if self._is_multi_value_field(canonical_field):
            return self._normalize_multi_value_cell(
                raw_value,
                canonical_field=canonical_field,
                row_index=row_index,
                row_warnings=row_warnings,
            )

        if canonical_field == "source_confidence":
            return self.normalize_value(raw_value).casefold()

        return self.normalize_value(raw_value, max_length=None)

    def _normalize_url_cell(
        self,
        raw_value: str,
        *,
        row_index: int,
        row_warnings: list[ValidationWarning],
    ) -> str:
        urls = [token.rstrip(").,;") for token in self._URL_PATTERN.findall(raw_value)]
        if len(urls) > 1:
            row_warnings.append(
                self._warning(
                    code="multiple_urls",
                    message=(
                        "Multiple URLs found; kept primary URL "
                        f"'{urls[0]}'."
                    ),
                    row_index=row_index,
                    field_name="lcsc_link",
                )
            )
            return urls[0]

        if urls:
            return urls[0]

        tokens = self.split_multi_value(raw_value)
        if len(tokens) > 1:
            row_warnings.append(
                self._warning(
                    code="multiple_urls",
                    message=(
                        "Multiple URL-like values found; kept primary value "
                        f"'{tokens[0]}'."
                    ),
                    row_index=row_index,
                    field_name="lcsc_link",
                )
            )
            return tokens[0]

        return self.normalize_value(raw_value, max_length=None)

    def _normalize_multi_value_cell(
        self,
        raw_value: str,
        *,
        canonical_field: str,
        row_index: int,
        row_warnings: list[ValidationWarning],
    ) -> str:
        tokens = self.split_multi_value(raw_value)
        if len(tokens) > 1:
            row_warnings.append(
                self._warning(
                    code="multiple_values",
                    message=(
                        f"Multiple {canonical_field.replace('_', ' ')} values "
                        f"found; kept primary value '{tokens[0]}'."
                    ),
                    row_index=row_index,
                    field_name=canonical_field,
                )
            )
            return tokens[0]

        if tokens:
            return tokens[0]

        return self.normalize_value(raw_value, max_length=None)

    def _resolve_quantity(self, *, designator_text: str, mapped_quantity: str) -> int:
        parsed_designators = self.parse_designators(designator_text)
        if parsed_designators:
            return len(parsed_designators)

        quantity_text = self.normalize_value(mapped_quantity, max_length=None)
        if not quantity_text:
            return 0

        match = re.search(r"\d+", quantity_text)
        if match is None:
            return 0
        return int(match.group(0))

    def _is_value_like_source(
        self,
        canonical_mappings: Mapping[str, str],
        canonical_field: str,
    ) -> bool:
        raw_column = canonical_mappings.get(canonical_field, "")
        return self.normalize_header(raw_column) in self._VALUE_ALIASES

    def _is_multi_value_field(self, canonical_field: str) -> bool:
        if canonical_field in {
            "lcsc_part_number",
            "mpn",
            "replacement_candidate_part_number",
            "replacement_candidate_mpn",
        }:
            return True
        return canonical_field.endswith("_link") or canonical_field.endswith("_url")

    def _row_has_meaningful_content(self, row_kwargs: Mapping[str, Any]) -> bool:
        tracked_fields = (
            "designator",
            "comment",
            "value_raw",
            "footprint",
            "lcsc_link",
            "lcsc_part_number",
            "manufacturer",
            "mpn",
            "package",
            "category",
            "param_summary",
            "source_url",
            "source_name",
            "source_confidence",
            "sourcing_notes",
            "replacement_candidate_part_number",
            "replacement_candidate_link",
            "replacement_candidate_mpn",
            "replacement_rationale",
            "replacement_status",
            "enrichment_provider",
            "enrichment_model",
            "enrichment_job_id",
            "enrichment_version",
            "evidence_blob",
            "raw_provider_response",
        )
        for field_name in tracked_fields:
            value = row_kwargs.get(field_name, "")
            if isinstance(value, str) and value:
                return True
            if isinstance(value, int) and value != 0:
                return True
        return False

    def _warning(
        self,
        *,
        code: str,
        message: str,
        row_index: int,
        field_name: str | None = None,
        severity: Confidence = Confidence.MEDIUM,
    ) -> ValidationWarning:
        return ValidationWarning(
            code=code,
            message=message,
            row_index=row_index,
            field_name=field_name,
            severity=severity,
        )

    def _serialize_warnings(self, warnings: Sequence[ValidationWarning]) -> str:
        payload = [warning.model_dump(mode="json") for warning in warnings]
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def _normalize_cell_text(self, raw_value: Any) -> str:
        if raw_value is None:
            return ""

        if isinstance(raw_value, list):
            parts = [self._normalize_cell_text(item) for item in raw_value]
            text = " ".join(part for part in parts if part)
        elif isinstance(raw_value, tuple):
            parts = [self._normalize_cell_text(item) for item in raw_value]
            text = " ".join(part for part in parts if part)
        else:
            text = self.normalize_value(raw_value, max_length=None)

        return text
