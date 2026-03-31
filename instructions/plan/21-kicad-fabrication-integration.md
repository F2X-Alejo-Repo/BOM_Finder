# KiCad & Fabrication Integration Plan

## Overview

This document captures the full integration roadmap for deepening BOM Workbench's
native support for KiCad workflows and PCB fabrication/assembly services (JLCPCB, LCSC).

**Driver**: F2X engineers work in KiCad and order assembly through JLCPCB/LCSC.
The current tool already handles the core BOM pipeline, but several friction points
remain between the KiCad design world and the ordering/fabrication world.

---

## Current State (as of 2026-03-30)

### What already works for KiCad users

| Capability | Status |
|---|---|
| Import KiCad-exported CSV BOM | Working — column matcher recognizes KiCad headers |
| Parse KiCad reference designators (R1, C2, U3) | Working |
| Designator range expansion (R1-R10 → list) | Working |
| Export 5-column procurement BOM (Designator, Comment, Footprint, LCSC LINK, LCSC PART #) | Working |
| LCSC part lookup and enrichment | Working |
| JLCPCB fallback for out-of-stock LCSC parts | Working (added 2026-03-30) |

### Known gaps

| Gap | Impact |
|---|---|
| KiCad exports footprints as `Library:Footprint_Name` — full string stored verbatim | Hurts LCSC/JLCPCB search accuracy; `Capacitor_SMD:C_0603_1608Metric` should match as `0603` |
| No dedicated JLCPCB assembly BOM export preset | User must manually verify column names match JLCPCB requirements |
| No pick-and-place / CPL file import | No cross-validation between BOM designators and placement file |
| No KiCad native file import (`.kicad_sch`, `.xml` netlist) | Users must export CSV manually; custom symbol fields (LCSC, MPN) ignored |
| No fabrication readiness report | No single view showing ordering blockers before placing order |
| No KiCad IPC/back-annotation | Changes in BOM Workbench don't flow back to schematic |

---

## Integration Tiers

### Tier 1 — High value, low effort (immediate)

#### 1.1 KiCad footprint stripping

**Problem**: KiCad exports footprints in `Library:Footprint_Name` format.
The app stores and searches using the full string, which never matches LCSC's
package identifiers (`0603`, `SOT-23`, `SOIC-8`, etc.).

**Solution**:
- In `infrastructure/csv/normalizer.py`, after column mapping, apply a
  `normalize_kicad_footprint(raw: str) -> tuple[str, str]` function that:
  - Splits on `:` and takes the right-hand part
  - Extracts the IPC package code from the footprint name using regex
    (e.g., `C_0603_1608Metric` → `0603`, `R_0402_1005Metric` → `0402`)
  - Known patterns: `{Component}_{Package}_{Metric}` → extract `{Package}`
- Store raw KiCad footprint in a new field `kicad_footprint` (or in `_extra_columns`)
- Store normalized package size in existing `footprint` / `package` fields
- Update `BomRow` if a schema migration is needed (add `kicad_footprint` column)

**Affected files**:
- `src/bom_workbench/infrastructure/csv/normalizer.py`
- `src/bom_workbench/domain/entities.py` (optional: add `kicad_footprint` field)
- `src/bom_workbench/infrastructure/csv/column_matcher.py` (if footprint alias tweaks needed)

**Acceptance**: Parts searched with `Capacitor_SMD:C_0603_1608Metric` footprint
resolve to `0603` and find matching LCSC parts at the same rate as parts entered
with a plain `0603` footprint.

---

#### 1.2 JLCPCB assembly BOM export preset

**Problem**: JLCPCB assembly service requires an exact column format:
- `Comment` — component value/description
- `Designator` — reference designators (comma-separated)
- `Footprint` — package (plain, not `Library:Name`)
- `LCSC Part #` — C-number

The current export uses `LCSC LINK` and `LCSC PART #` which may not match
JLCPCB's import template exactly. Additionally column ordering matters.

**Solution**:
- Add a new export target `jlcpcb_assembly_bom` to `XlsxExporter`
- Columns (exact names and order):
  1. `Comment` ← `comment`
  2. `Designator` ← `designator`
  3. `Footprint` ← `footprint` (normalized, not raw KiCad path)
  4. `LCSC Part #` ← `lcsc_part_number`
- Output as `.xlsx` (JLCPCB accepts xlsx or csv)
- Add a CSV variant as well (`jlcpcb_assembly_bom_csv`)
- Add "JLCPCB Assembly BOM" option to the Export page UI
- Flag rows missing `lcsc_part_number` in this export mode (they'll fail JLCPCB upload)

**Affected files**:
- `src/bom_workbench/infrastructure/exporters/xlsx_exporter.py`
- `src/bom_workbench/ui/pages/export_page.py`
- `src/bom_workbench/application/export_bom.py` (if export target enum lives here)

**Acceptance**: Exported file uploads to JLCPCB assembly order without column
mapping errors. Missing LCSC part numbers are visually flagged in the file.

---

#### 1.3 Pick-and-place / CPL file import

**Problem**: JLCPCB also requires a Component Placement List (CPL) alongside the BOM.
KiCad exports this as a CSV with columns: `Ref`, `Val`, `Package`, `PosX`, `PosY`,
`Rot`, `Side`. If designators in the BOM and CPL don't match, the order fails.

**Solution**:
- Add a secondary import slot on the Import page: "Pick & Place file (optional)"
- Parse CPL CSV (same CSV parser already in use), map columns:
  - `Ref`/`Reference` → designator
  - `PosX`/`Mid X` → x_pos
  - `PosY`/`Mid Y` → y_pos
  - `Rot`/`Rotation` → rotation
  - `Side`/`Layer` → layer (`Top`/`Bottom`)
- Store CPL data in a new `CplEntry` table (or as JSON on BomProject)
- Cross-validate: warn if a BOM designator has no CPL entry, and vice versa
- Include CPL pass-through in JLCPCB export (copy CPL file alongside BOM, or merge into export package)
- Optionally: generate a JLCPCB-formatted CPL output file

**New domain entity**:
```python
class CplEntry(SQLModel):
    id: int | None
    project_id: int          # FK to BomProject
    designator: str          # e.g., "R1"
    x_pos: float             # mm
    y_pos: float             # mm
    rotation: float          # degrees
    layer: str               # "Top" or "Bottom"
    source_file: str         # original CPL filename
```

**Affected files**:
- `src/bom_workbench/domain/entities.py` (new `CplEntry`)
- `src/bom_workbench/infrastructure/csv/` (new `cpl_parser.py`)
- `src/bom_workbench/ui/pages/import_page.py`
- `src/bom_workbench/ui/pages/export_page.py`

**Acceptance**: A KiCad CPL file imported alongside a BOM shows a validation
summary. Missing designators are flagged. JLCPCB export includes both BOM and CPL.

---

### Tier 2 — Medium effort, high value

#### 2.1 KiCad XML netlist import

KiCad's built-in BOM plugin can export a structured XML netlist containing all
components with all symbol fields (Value, Footprint, Datasheet, and any custom
fields like `LCSC`, `MPN`, `Manufacturer`).

**Format**: KiCad XML netlist (`*.xml`) — each component is:
```xml
<comp ref="C1">
  <value>100nF</value>
  <footprint>Capacitor_SMD:C_0603_1608Metric</footprint>
  <fields>
    <field name="LCSC">C14663</field>
    <field name="MPN">CC0603KRX7R9BB104</field>
    <field name="Manufacturer">YAGEO</field>
  </fields>
</comp>
```

**Solution**:
- Add `infrastructure/parsers/kicad_netlist_parser.py`
- Use Python's `xml.etree.ElementTree` (stdlib, no new dependency)
- Map fields: `ref→designator`, `value→comment`, `footprint→footprint`,
  custom `LCSC→lcsc_part_number`, custom `MPN→mpn`, custom `Manufacturer→manufacturer`
- Normalize footprint using the same stripping logic from Tier 1.1
- Add XML file drop zone / import button on Import page alongside CSV

**Acceptance**: A KiCad XML netlist imports with all custom fields pre-populated.
Parts with `LCSC` field filled skip the retrieval step and go straight to enrichment.

---

#### 2.2 KiCad `.kicad_sch` direct import

KiCad 6+ stores schematics as S-expression text files (`.kicad_sch`).
Parsing directly eliminates the need to export anything from KiCad.

**Format** (simplified S-expression):
```
(symbol (property "Reference" "C1") (property "Value" "100nF")
        (property "Footprint" "Capacitor_SMD:C_0603_1608Metric")
        (property "LCSC" "C14663"))
```

**Solution**:
- Add `infrastructure/parsers/kicad_sch_parser.py`
- Implement a minimal S-expression tokenizer (no external lib needed)
- Extract `symbol` blocks with their `property` children
- Hierarchical schematic support: follow `sheet` references to sub-sheets
- Auto-detect file type on drop (`.kicad_sch` vs `.csv` vs `.xml`)

**Acceptance**: Dropping a `.kicad_sch` file onto the import zone produces the
same BOM as KiCad's own CSV export, plus any custom fields the engineer added.

---

#### 2.3 Fabrication readiness report

After enrichment, surface a single pre-order checklist:

| Check | Condition | Severity |
|---|---|---|
| Missing LCSC Part # | `lcsc_part_number` empty | Error — JLCPCB won't accept |
| Out of stock | `stock_status == "out"` and no JLCPCB alternative | Error |
| Out of stock with JLCPCB alternative | JLCPCB has stock | Warning — confirm switch |
| Below MOQ | `quantity < moq` | Warning — will be rounded up |
| EOL / NRND | `lifecycle_status in {"eol", "nrnd"}` | Warning — source alternative |
| CPL mismatch | Designator in BOM but not in CPL | Error |
| High lead time | `lead_time` mentions weeks/months | Info |

**Solution**:
- Add `application/fabrication_check.py` use case
- Add "Fabrication Check" page or panel to UI
- Export checklist as PDF or include as a sheet in the JLCPCB export package

---

### Tier 3 — Higher effort, optional

#### 3.1 KiCad IPC-API connection (KiCad 8+)

KiCad 8 introduced a gRPC-based IPC API on `localhost:50051`.
BOM Workbench could query a running KiCad instance directly.

**Requirements**:
- `grpcio` + `grpcio-tools` dependency
- KiCad IPC protobuf definitions (from KiCad repo: `kicad/api/proto/`)
- KiCad must be running with IPC enabled

**Capabilities unlocked**:
- Read schematic components live (no export step)
- Push LCSC part numbers back into schematic symbols
- Trigger DRC or netlist refresh from BOM Workbench

**Decision gate**: Implement only if user runs KiCad 8+ and needs live two-way sync.
The XML netlist approach (Tier 2.1) covers 95% of use cases with zero dependency.

---

#### 3.2 Back-annotation

After enrichment, write resolved data (LCSC part numbers, MPNs, manufacturers)
back into the KiCad schematic:
- Via IPC API (Tier 3.1) — cleanest, no file surgery
- Via direct `.kicad_sch` edit — parse, update property values, write back
- Risk: corrupts schematic if S-expression write is incorrect → require backup

---

#### 3.3 File watcher

Watch a KiCad project folder for changes to `.kicad_sch` files. On save,
auto-reload the import and flag changed components. Useful for iterative
design where the schematic evolves alongside the BOM review.

**Implementation**: Python `watchdog` library (one new dependency).

---

## Connection Method Summary

| Method | Complexity | KiCad Version | Direction | Dependency |
|---|---|---|---|---|
| CSV import (current) | Done | All | KiCad → App | None |
| XML netlist import | Low | All | KiCad → App | None (stdlib xml) |
| `.kicad_sch` parser | Medium | 6+ | KiCad → App | None |
| IPC gRPC API | High | 8+ | Both ways | `grpcio` |
| KiCad plugin | High | All | Both ways | Runs inside KiCad |
| File watcher | Low-medium | All | KiCad → App | `watchdog` |

**Recommended path**: CSV (done) → XML netlist → `.kicad_sch` → IPC (if needed).

---

## Implementation Order

```
Tier 1.1  Footprint stripping          ← start here (fixes search quality)
Tier 1.2  JLCPCB export preset        ← then this (ordering workflow)
Tier 1.3  CPL import + validation      ← then this (fabrication safety)
Tier 2.1  XML netlist import           ← next major milestone
Tier 2.2  .kicad_sch parser           ← after XML, same infrastructure
Tier 2.3  Fabrication readiness report ← after CPL import
Tier 3.1  IPC API                      ← only if live sync is required
Tier 3.2  Back-annotation              ← after IPC or .kicad_sch parser
Tier 3.3  File watcher                 ← last, quality-of-life
```

---

## Files to Create / Modify

### Tier 1 new/modified files

| File | Change |
|---|---|
| `src/bom_workbench/infrastructure/csv/normalizer.py` | Add `normalize_kicad_footprint()` |
| `src/bom_workbench/domain/entities.py` | Add `kicad_footprint` field (optional) |
| `src/bom_workbench/infrastructure/exporters/xlsx_exporter.py` | Add `jlcpcb_assembly_bom` target |
| `src/bom_workbench/ui/pages/export_page.py` | Add JLCPCB export option to UI |
| `src/bom_workbench/infrastructure/csv/cpl_parser.py` | **New** — CPL file parser |
| `src/bom_workbench/domain/entities.py` | **New** `CplEntry` entity |
| `src/bom_workbench/ui/pages/import_page.py` | Add CPL file drop zone |
| `tests/unit/test_kicad_footprint_normalizer.py` | **New** — unit tests |
| `tests/unit/test_jlcpcb_export.py` | **New** — export format tests |
| `tests/unit/test_cpl_parser.py` | **New** — CPL parser tests |

### Tier 2 new files

| File | Change |
|---|---|
| `src/bom_workbench/infrastructure/parsers/kicad_netlist_parser.py` | **New** |
| `src/bom_workbench/infrastructure/parsers/kicad_sch_parser.py` | **New** |
| `src/bom_workbench/application/fabrication_check.py` | **New** |
| `src/bom_workbench/ui/pages/fabrication_page.py` | **New** |
