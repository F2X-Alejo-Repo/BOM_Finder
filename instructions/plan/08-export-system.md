# 08 — Export System

## Export Targets

| Target | Columns | Use Case |
|--------|---------|----------|
| **Procurement BOM** (primary) | Designator, Comment, Footprint, LCSC LINK, LCSC PART # | Final clean output for ordering |
| **Full canonical table** | All canonical fields | Full data dump for analysis |
| **Current filtered view** | Currently visible columns | What user sees on screen |

## XlsxExporter Design

```python
class XlsxExporter(IExporter):
    """Generates professionally formatted Excel files using openpyxl."""

    async def export_procurement_bom(
        self,
        rows: list[BomRow],
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult: ...

    async def export_full_table(
        self,
        rows: list[BomRow],
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult: ...

    async def export_filtered_view(
        self,
        rows: list[BomRow],
        columns: list[str],
        output_path: Path,
        options: ExportOptions,
    ) -> ExportResult: ...
```

## Procurement BOM Format (Primary Export)

### Sheet: "BOM"

| Column | Width | Alignment | Source Field |
|--------|-------|-----------|-------------|
| A: Designator | 20 | Left | `designator` |
| B: Comment | 25 | Left | `comment` |
| C: Footprint | 25 | Left | `footprint` |
| D: LCSC LINK | 40 | Left | `lcsc_link` (hyperlink) |
| E: LCSC PART # | 18 | Left | `lcsc_part_number` |

### Formatting Rules

```python
# Header row (row 1)
header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
header_alignment = Alignment(horizontal="left", vertical="center", wrap_text=False)
header_border = Border(bottom=Side(style="thin", color="4a9eff"))

# Data rows (row 2+)
data_font = Font(name="Segoe UI", size=10, color="333333")
data_alignment = Alignment(horizontal="left", vertical="center")

# LCSC LINK column — make clickable hyperlinks
for row in data_rows:
    if row.lcsc_link:
        cell.hyperlink = row.lcsc_link
        cell.font = Font(name="Segoe UI", size=10, color="4a9eff", underline="single")

# Auto-filter on header row
sheet.auto_filter.ref = f"A1:E{len(rows) + 1}"

# Freeze top row
sheet.freeze_panes = "A2"

# Column widths
sheet.column_dimensions["A"].width = 20
sheet.column_dimensions["B"].width = 25
sheet.column_dimensions["C"].width = 25
sheet.column_dimensions["D"].width = 40
sheet.column_dimensions["E"].width = 18
```

### Sheet: "Metadata" (optional, controlled by ExportOptions)

| Row | Content |
|-----|---------|
| 1 | **Export Metadata** (bold header) |
| 2 | Export timestamp: 2026-03-27 14:32:01 UTC |
| 3 | Source files: sample_bom.csv, power_board.csv |
| 4 | Total rows: 142 |
| 5 | Rows enriched: 89 |
| 6 | Rows with warnings: 12 |
| 7 | Provider used: Anthropic / claude-sonnet-4 |
| 8 | Export target: Procurement BOM |
| 9 | (blank) |
| 10 | **Warnings Summary** (bold) |
| 11+ | One row per warning, grouped by severity |

## Export Options

```python
class ExportOptions(BaseModel):
    include_metadata_sheet: bool = True
    apply_color_coding: bool = True      # Color code status in full table export
    preserve_hyperlinks: bool = True
    sanitize_formulas: bool = True       # Prevent formula injection
```

## Formula Sanitization

To prevent formula injection (cells starting with `=`, `+`, `-`, `@`):

```python
def sanitize_cell(value: str) -> str:
    """Prevent formula injection in Excel cells."""
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value  # Prefix with single quote (Excel treats as text)
    return value
```

## ExportResult

```python
class ExportResult(BaseModel):
    output_path: str
    rows_exported: int
    sheets_created: list[str]
    warnings: list[str]
    duration_seconds: float
    file_size_bytes: int
```

## UTF-8 Handling

- All string values encoded as UTF-8
- openpyxl handles Unicode natively
- BOM marker not added (openpyxl default is correct)
- Test with accented characters, CJK text, special symbols
