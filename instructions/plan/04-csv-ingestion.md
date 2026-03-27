# 04 — CSV Ingestion Pipeline

## Overview

The CSV ingestion pipeline transforms raw KiCad 9 BOM CSV files into canonical `BomRow` entities. It must handle arbitrary column ordering, naming variations, encoding, and partial corruption — never silently dropping data.

## Pipeline Stages

```
File(s) selected / dropped
    │
    ▼
┌─────────────────────────────┐
│ 1. FILE DETECTION           │
│    - Validate file exists   │
│    - Detect encoding        │
│      (chardet/charset_norm) │
│    - Detect BOM marker      │
│    - Read raw bytes         │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 2. DELIMITER DETECTION      │
│    - csv.Sniffer on first   │
│      10 lines               │
│    - Fallback: comma        │
│    - Support: , ; \t |      │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 3. HEADER PARSING           │
│    - Read first row         │
│    - Strip whitespace       │
│    - Feed to ColumnMatcher  │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 4. COLUMN MATCHING          │
│    - Regex-driven matching  │
│    - Generate ColumnMapping │
│    - Flag unmapped columns  │
│    - Flag ambiguous matches │
└──────────┬──────────────────┘
           ▼
┌──────────────────────────────────┐
│ 5. USER PREVIEW (UI Dialog)      │
│    - Show detected mappings      │
│    - Allow manual override       │
│    - Show warnings               │
│    - Confirm or cancel           │
└──────────┬───────────────────────┘
           ▼
┌─────────────────────────────┐
│ 6. ROW PARSING              │
│    - pandas.read_csv with   │
│      detected params        │
│    - Handle quoted fields   │
│    - Handle multiline cells │
│    - Preserve all columns   │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 7. NORMALIZATION            │
│    - Map raw cols → canon   │
│    - Parse designator lists │
│    - Compute quantity       │
│    - Extract value_raw      │
│    - Clean whitespace       │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 8. VALIDATION               │
│    - Check required fields  │
│    - Flag empty designators │
│    - Flag ambiguous URLs    │
│    - Flag duplicate part #  │
│    - Generate warnings      │
│    - NEVER drop rows        │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ 9. PERSISTENCE              │
│    - Create BomProject      │
│    - Insert BomRow records  │
│    - Store validation warns │
│    - Generate ImportReport  │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────────┐
│ 10. IMPORT REPORT (UI Dialog)   │
│     - Rows imported / skipped   │
│     - Warnings summary          │
│     - Unmapped columns          │
│     - Duration                  │
└─────────────────────────────────┘
```

## Column Matcher — Regex Alias Map

The `ColumnMatcher` class (`infrastructure/csv/column_matcher.py`) holds a registry of canonical fields and their regex patterns. Before matching, the raw column name is pre-processed:

### Pre-processing (applied to raw column name before regex)
1. Strip leading/trailing whitespace
2. Convert to lowercase
3. Replace underscores, hyphens, dots with spaces
4. Collapse multiple spaces to single space
5. Strip remaining non-alphanumeric except spaces

### Regex Alias Patterns

```python
COLUMN_ALIASES: dict[str, list[str]] = {
    "designator": [
        r"^designators?$",
        r"^references?$",
        r"^refs?$",
        r"^ref\s*des(ignators?)?$",
    ],
    "comment": [
        r"^comments?$",
        r"^values?$",
        r"^vals?$",
        r"^description$",
        r"^part\s*description$",
    ],
    "footprint": [
        r"^footprints?$",
        r"^packages?$",
        r"^pcb\s*footprints?$",
        r"^land\s*patterns?$",
    ],
    "lcsc_link": [
        r"^lcsc\s*links?$",
        r"^lcsc\s*urls?$",
        r"^supplier\s*links?$",
        r"^part\s*links?$",
        r"^supplier\s*urls?$",
    ],
    "lcsc_part_number": [
        r"^lcsc\s*part\s*(?:numbers?|#|no)$",
        r"^lcsc\s*(?:pn|no|#)$",
        r"^part\s*(?:numbers?|#)$",
        r"^supplier\s*part\s*(?:numbers?|#)$",
    ],
    # Additional optional columns for richer imports
    "manufacturer": [
        r"^manufacturers?$",
        r"^mfg$",
        r"^mfr$",
    ],
    "mpn": [
        r"^mpn$",
        r"^mfg\s*part\s*(?:numbers?|#)$",
        r"^manufacturer\s*part\s*(?:numbers?|#)$",
    ],
    "quantity": [
        r"^qty$",
        r"^quantity$",
        r"^count$",
    ],
}
```

### Matching Algorithm

```
for each raw_column in csv_headers:
    preprocessed = preprocess(raw_column)
    for canonical_field, patterns in COLUMN_ALIASES.items():
        for pattern in patterns:
            if re.match(pattern, preprocessed):
                record ColumnMapping(
                    raw_column=raw_column,
                    canonical_field=canonical_field,
                    confidence=1.0,
                    matched_by="regex"
                )
                break

    if no match found:
        mark as unmapped_column
```

If multiple raw columns match the same canonical field → flag ambiguity warning, pick first match, allow user override in preview dialog.

## Special Handling Rules

1. **"Value" → "comment"**: If only "Value" exists (no "Comment"), map it to `comment` while also storing the original in `value_raw`

2. **Multiple URLs in a cell**: If a cell contains multiple URLs (semicolon or comma separated), preserve all in `value_raw`, extract first valid LCSC URL as primary `lcsc_link`, flag with validation warning

3. **Multiple part numbers**: Same strategy — preserve all, pick primary, flag ambiguity

4. **Designator parsing**: "R1, R2, R3" → `designator_list = ["R1", "R2", "R3"]`, `quantity = 3`

5. **Malformed rows**: Never drop. Store with `row_state = "imported"` and `validation_warnings` populated

## CsvParser Class Design

```python
class CsvParser:
    """Parses raw CSV files into structured data with detected parameters."""

    def detect_encoding(self, file_path: Path) -> str:
        """Detect file encoding using charset_normalizer. Returns encoding string."""

    def detect_delimiter(self, file_path: Path, encoding: str) -> str:
        """Detect CSV delimiter using csv.Sniffer. Falls back to comma."""

    def parse(self, file_path: Path) -> ParseResult:
        """Full parse: detect params, read headers, read all rows."""

class ParseResult(BaseModel):
    file_path: str
    encoding: str
    delimiter: str
    headers: list[str]
    rows: list[dict[str, str]]  # raw row data
    row_count: int
    parse_warnings: list[str]
```

## RowNormalizer Class Design

```python
class RowNormalizer:
    """Transforms raw parsed rows into canonical BomRow entities."""

    def normalize(
        self,
        raw_rows: list[dict[str, str]],
        column_mappings: list[ColumnMapping],
        source_file: str,
        project_id: int,
    ) -> NormalizationResult:
        """Normalize all rows using confirmed column mappings."""

class NormalizationResult(BaseModel):
    rows: list[BomRow]
    warnings: list[ValidationWarning]
    skipped_count: int  # Should always be 0 per spec (never skip)
```

## Encoding Detection Library

Use `charset_normalizer` (pure Python, better than chardet for modern use):
- Handles UTF-8, UTF-8 BOM, Latin-1, Windows-1252, etc.
- Falls back to UTF-8 if detection confidence is low
